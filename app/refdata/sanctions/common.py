"""Shared helpers for sanction-source ingesters: upsert + companion country_rule rows."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CountryRule,
    HsCode,
    RefdataRun,
    SanctionedCommodity,
    SanctionedCommodityAlias,
)
from app.refdata.common import batches, lazy_embedder, mark_progress, update_tsv_for_table
from app.telemetry import log


async def upsert_sanctioned_commodities(
    db: AsyncSession,
    rows: list[dict],
    source: str,
    run: RefdataRun | None = None,
) -> dict[str, int]:
    """Upsert sanctioned_commodity rows, embedding descriptions in batches.

    Each input row supports: source_record_id, description, hs_codes (list of 6-digit strings),
    restriction_type, effective_from, effective_to, provenance_url, and an optional
    list of country_rules: [{origin_iso, destination_iso, restriction_type, conditions}].
    Returns counts.

    Idempotency: relies on `uq_sanctioned_commodity_source_recid` and `uq_country_rule`
    (migration 0005). Rows with NULL source_record_id are inserted each run because
    Postgres treats NULL as distinct in unique constraints — those rows have no
    stable identity to dedupe against.
    """
    if not rows:
        return {"sanctioned": 0, "rules": 0}
    embedder = lazy_embedder()
    n_sanctioned = 0
    n_rules = 0
    for batch in batches(rows, 64):
        descs = [r["description"] for r in batch]
        vectors = embedder.encode_batch(descs)
        for r, v in zip(batch, vectors, strict=True):
            stmt = insert(SanctionedCommodity).values(
                source=source,
                source_record_id=r.get("source_record_id"),
                description=r["description"],
                hs_codes=r.get("hs_codes") or [],
                restriction_type=r.get("restriction_type"),
                effective_from=r.get("effective_from"),
                effective_to=r.get("effective_to"),
                provenance_url=r.get("provenance_url"),
                embedding=v.tolist(),
            )
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_sanctioned_commodity_source_recid"
            )
            await db.execute(stmt)
            n_sanctioned += 1

            # Look up the row we just inserted (by source + source_record_id) to attach country_rules.
            if r.get("country_rules") and r.get("source_record_id"):
                got = (
                    await db.execute(
                        select(SanctionedCommodity.id).where(
                            SanctionedCommodity.source == source,
                            SanctionedCommodity.source_record_id == r["source_record_id"],
                        )
                    )
                ).scalar_one_or_none()
                if got is None:
                    continue
                for rule in r["country_rules"]:
                    cr = insert(CountryRule).values(
                        origin_iso=rule.get("origin_iso"),
                        destination_iso=rule.get("destination_iso"),
                        sanctioned_commodity_id=got,
                        restriction_type=rule.get("restriction_type") or r.get("restriction_type"),
                        conditions=rule.get("conditions"),
                        active=True,
                    ).on_conflict_do_nothing(constraint="uq_country_rule")
                    await db.execute(cr)
                    n_rules += 1
        if run is not None:
            await mark_progress(db, run, n_sanctioned)
        else:
            await db.commit()
        log.info("sanctions.upsert_progress", source=source, sanctioned=n_sanctioned, rules=n_rules)
    await update_tsv_for_table(db, "sanctioned_commodity", columns=("description",))
    await db.commit()
    return {"sanctioned": n_sanctioned, "rules": n_rules}


def normalize_cn_code(raw: str | None) -> str | None:
    """Normalize a single HS / CN code to 2-, 4-, or 6-digit form.

    Inputs longer than 6 digits (HS-8 CN codes, HS-10 HTS codes, etc.) are
    truncated to 6 — the HS-6 level is the international common denominator.
    Inputs of exactly 4 or 2 digits are kept as-is; they represent heading /
    chapter prefixes and need to be fanned out at ingest time via
    `expand_hs_prefixes` so the structured-overlap join (`&&`) at screen time
    actually matches 6-digit shipment classifications.
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    if len(digits) == 4:
        return digits
    if len(digits) == 2:
        return digits
    return None


def normalize_codes(raw: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        c = normalize_cn_code(r)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def expand_hs_prefixes(db: AsyncSession, codes: list[str]) -> list[str]:
    """Expand HS prefixes to the full set of matching 6-digit subheadings.

    A 6-digit code is returned as-is. A 2- or 4-digit code is expanded by querying
    `hs_code` for all 6-digit rows whose `code` starts with the prefix. Missing
    prefixes (e.g. HS taxonomy not yet loaded) are dropped with a warning — they'd
    otherwise persist as non-matching strings in `sanctioned_commodity.hs_codes`
    and silently fail the `&&` overlap join at screening time.

    Hoisted from app/refdata/sanctions/country_program/ingest.py so every
    sanctions ingester can use it without duplicating the helper.
    """
    if not codes:
        return []
    out: set[str] = set()
    for c in codes:
        if len(c) == 6:
            out.add(c)
            continue
        rows = (
            await db.execute(
                select(HsCode.code).where(
                    HsCode.code.like(f"{c}%"),
                    HsCode.level == 6,
                )
            )
        ).scalars().all()
        if not rows:
            log.warning("sanctions.unexpanded_prefix", prefix=c)
            continue
        out.update(rows)
    return sorted(out)


async def expand_rows_in_place(db: AsyncSession, rows: list[dict]) -> None:
    """Expand `hs_codes` in each row dict against the live HS taxonomy."""
    for r in rows:
        r["hs_codes"] = await expand_hs_prefixes(db, r.get("hs_codes") or [])


async def insert_aliases(
    db: AsyncSession,
    *,
    source: str,
    source_record_id: str,
    aliases: list[dict],
) -> int:
    """Insert aliases for a previously-upserted sanctioned_commodity.

    Each alias is `{"alias": str, "alias_kind": str | None}`. Idempotent via
    `uq_alias_per_commodity` (migration 0003). Returns the number of INSERTs
    attempted (NOT the number actually written — ON CONFLICT swallows duplicates).
    """
    if not aliases:
        return 0
    sid = (
        await db.execute(
            select(SanctionedCommodity.id).where(
                SanctionedCommodity.source == source,
                SanctionedCommodity.source_record_id == source_record_id,
            )
        )
    ).scalar_one_or_none()
    if sid is None:
        return 0
    n = 0
    for a in aliases:
        alias_text = (a.get("alias") or "").strip()
        if not alias_text:
            continue
        stmt = insert(SanctionedCommodityAlias).values(
            sanctioned_commodity_id=sid,
            alias=alias_text[:500],
            alias_kind=a.get("alias_kind"),
        ).on_conflict_do_nothing(constraint="uq_alias_per_commodity")
        await db.execute(stmt)
        n += 1
    return n
