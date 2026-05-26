"""Shared helpers for sanction-source ingesters: bitemporal upsert + country_rule rows."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    CountryRule,
    HsCode,
    RefdataRun,
    SanctionedCommodity,
    SanctionedCommodityAlias,
)
from app.refdata.common import batches, lazy_embedder, mark_progress
from app.telemetry import log


def _canonical(value):
    """Deterministic, JSON-serializable projection for content hashing."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    return value


def content_hash(row: dict) -> bytes:
    """SHA-256 over the audit-relevant fields of a source row.

    Drives bitemporal change detection: a row whose hash is unchanged is skipped;
    a changed hash closes the current version and opens a new one. The embedding is
    excluded (it is derived from `description`, which is hashed). hs_codes are sorted
    so list-order churn is not mistaken for a real change.
    """
    payload = {
        "description": row.get("description") or "",
        "hs_codes": sorted(row.get("hs_codes") or []),
        "restriction_type": row.get("restriction_type"),
        "effective_from": row.get("effective_from"),
        "effective_to": row.get("effective_to"),
        "provenance_url": row.get("provenance_url"),
        "program_tag": row.get("program_tag"),
        "country_rules": sorted(
            (
                {
                    "origin_iso": cr.get("origin_iso"),
                    "destination_iso": cr.get("destination_iso"),
                    "restriction_type": cr.get("restriction_type"),
                    "conditions": cr.get("conditions"),
                }
                for cr in (row.get("country_rules") or [])
            ),
            key=lambda d: json.dumps(_canonical(d), sort_keys=True),
        ),
    }
    blob = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).digest()


async def _replace_country_rules(db: AsyncSession, commodity_pk: int, row: dict) -> int:
    """Point the row's country_rules at the live version `commodity_pk`.

    Deletes any rules already attached to this version (none for a brand-new
    version) and inserts the desired set. Returns the number inserted.
    """
    await db.execute(
        CountryRule.__table__.delete().where(CountryRule.sanctioned_commodity_id == commodity_pk)
    )
    n = 0
    for rule in row.get("country_rules") or []:
        await db.execute(
            insert(CountryRule)
            .values(
                origin_iso=rule.get("origin_iso"),
                destination_iso=rule.get("destination_iso"),
                sanctioned_commodity_id=commodity_pk,
                restriction_type=rule.get("restriction_type") or row.get("restriction_type"),
                conditions=rule.get("conditions"),
                active=True,
            )
            .on_conflict_do_nothing(constraint="uq_country_rule")
        )
        n += 1
    return n


async def upsert_sanctioned_commodities(
    db: AsyncSession,
    rows: list[dict],
    source: str,
    run: RefdataRun | None = None,
) -> dict[str, int]:
    """Content-hash-driven bitemporal upsert into sanctioned_commodity (item 7).

    Each input row supports: source_record_id, description, hs_codes (list of 6-digit
    strings), restriction_type, effective_from, effective_to, provenance_url,
    program_tag, and an optional list of country_rules.

    For every row keyed by (source, source_record_id): unchanged content is a no-op;
    changed content closes the current version (sets sys_to=now()) and opens a new one
    sharing the same commodity_id; a never-seen key inserts a new logical commodity.
    Rows present in the DB but absent from this refresh are logically deleted by
    closing their current version — scoped `AND source = :source` so one source's
    refresh never closes another source's rows. description_tsv is a generated column
    (migration 0009), so no explicit tsvector maintenance is needed here.
    """
    if not rows:
        return {"sanctioned": 0, "rules": 0}
    embedder = lazy_embedder()
    model_name = settings.embedder_model
    n_changed = 0
    n_rules = 0
    seen_recids: list[str] = []

    for batch in batches(rows, 64):
        # Resolve current state for the batch's keyed rows first; only embed the
        # rows that are new or whose content changed.
        to_embed: list[dict] = []
        for r in batch:
            recid = r.get("source_record_id")
            if recid is not None:
                seen_recids.append(recid)
            h = content_hash(r)
            r["_hash"] = h
            current = (
                await db.execute(
                    select(SanctionedCommodity.id, SanctionedCommodity.commodity_id, SanctionedCommodity.content_hash).where(
                        SanctionedCommodity.source == source,
                        SanctionedCommodity.source_record_id.is_not_distinct_from(recid),
                        SanctionedCommodity.sys_to.is_(None),
                    )
                )
            ).first()
            r["_current"] = current
            if current is None or bytes(current.content_hash or b"") != h:
                to_embed.append(r)

        vectors = embedder.encode_batch([r["description"] for r in to_embed]) if to_embed else []
        for r, v in zip(to_embed, vectors, strict=True):
            current = r["_current"]
            commodity_id = current.commodity_id if current is not None else None
            if current is not None:
                # Close the stale version.
                await db.execute(
                    update(SanctionedCommodity)
                    .where(SanctionedCommodity.id == current.id)
                    .values(sys_to=func.now())
                )
            values = dict(
                source=source,
                source_record_id=r.get("source_record_id"),
                description=r["description"],
                hs_codes=r.get("hs_codes") or [],
                restriction_type=r.get("restriction_type"),
                effective_from=r.get("effective_from"),
                effective_to=r.get("effective_to"),
                provenance_url=r.get("provenance_url"),
                program_tag=r.get("program_tag"),
                embedding=v.tolist(),
                embedding_model=model_name,
                content_hash=r["_hash"],
            )
            if commodity_id is not None:
                values["commodity_id"] = commodity_id  # new version of an existing commodity
            new_pk = (
                await db.execute(
                    insert(SanctionedCommodity).values(**values).returning(SanctionedCommodity.id)
                )
            ).scalar_one()
            n_changed += 1
            n_rules += await _replace_country_rules(db, new_pk, r)

        if run is not None:
            await mark_progress(db, run, n_changed)
        else:
            await db.commit()
        log.info("sanctions.upsert_progress", source=source, changed=n_changed, rules=n_rules)

    # Logical delete: close current versions for this source that vanished from the
    # feed. Guarded on having seen stable record IDs — a feed of only NULL-id rows
    # must not close the source's keyed history.
    closed_ids: list[int] = []
    if seen_recids:
        closed = await db.execute(
            text(
                """
                UPDATE sanctioned_commodity
                   SET sys_to = now()
                 WHERE source = :source
                   AND sys_to IS NULL
                   AND source_record_id IS NOT NULL
                   AND NOT (source_record_id = ANY(:recids))
                RETURNING id
                """
            ),
            {"source": source, "recids": seen_recids},
        )
        closed_ids = [row[0] for row in closed.fetchall()]
    if closed_ids:
        await db.execute(
            update(CountryRule)
            .where(CountryRule.sanctioned_commodity_id.in_(closed_ids))
            .values(active=False)
        )
    await db.commit()
    return {"sanctioned": n_changed, "rules": n_rules, "closed": len(closed_ids)}


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
                SanctionedCommodity.sys_to.is_(None),
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
