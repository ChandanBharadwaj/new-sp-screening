"""Shared helpers for sanction-source ingesters: upsert + companion country_rule rows."""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CountryRule, SanctionedCommodity
from app.refdata.common import batches, lazy_embedder, update_tsv_for_table
from app.telemetry import log


async def upsert_sanctioned_commodities(
    db: AsyncSession,
    rows: list[dict],
    source: str,
) -> dict[str, int]:
    """Upsert sanctioned_commodity rows, embedding descriptions in batches.

    Each input row supports: source_record_id, description, hs_codes (list of 6-digit strings),
    restriction_type, effective_from, effective_to, provenance_url, and an optional
    list of country_rules: [{origin_iso, destination_iso, restriction_type, conditions}].
    Returns counts.
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
            stmt = stmt.on_conflict_do_nothing()
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
                    )
                    await db.execute(cr)
                    n_rules += 1
        await db.commit()
        log.info("sanctions.upsert_progress", source=source, sanctioned=n_sanctioned, rules=n_rules)
    await update_tsv_for_table(db, "sanctioned_commodity", columns=("description",))
    await db.commit()
    return {"sanctioned": n_sanctioned, "rules": n_rules}


def normalize_cn_code(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) < 6:
        return None
    return digits[:6]


def normalize_codes(raw: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        c = normalize_cn_code(r)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
