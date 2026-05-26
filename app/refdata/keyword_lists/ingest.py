"""Ingester for operator-authored keyword lists.

A keyword list (e.g. "seafood") is a CSV with a single `keywords` column where each
row is a sanctioned word or short phrase. Per the unified data-layer design, this
ingester does not create rules directly: it lands each keyword as a
`sanctioned_commodity` row under `source = "KW:<list_name>"`, attaches companion
`country_rule` rows for the list's origin/destination scope, and then enables
materialization for that source so the existing
`app.refdata.sanctions.materialize_rules.materialize_for_source` derives one
`screening_rule` per keyword.

Result: keyword lists ride on the same scoring path as OFAC, EU, BIS, ITAR, UN,
and country-program data — `app/pipeline/sanctions.py` for sanctions matching,
`app/pipeline/rules.py` for semantic rule scoring. No duplicate code, no
parallel taxonomy.

CSV shape (case-insensitive header match):

    keywords
    yellowfin tuna
    bluefin tuna
    caviar
    ...

Re-upload semantics: keyword lists are *full replacements*. Re-ingesting the
same list goes through the bitemporal upsert, which closes the current version
(logical delete) of any keyword whose `source_record_id` no longer appears in
the new CSV, preserving history. The materializer's orphan-soft-deactivation
path then deactivates the corresponding `screening_rule` rows.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    KeywordList,
    SanctionsRuleConfig,
)
from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import upsert_sanctioned_commodities
from app.telemetry import configure_logging, log

SOURCE_PREFIX = "KW:"
VALID_DIRECTIONS = ("import_from", "export_to", "both")
MIN_KEYWORD_LEN = 3
MAX_KEYWORD_LEN = 2000


def source_key(list_name: str) -> str:
    """Build the `sanctioned_commodity.source` value for a keyword list.

    Keep the prefix short — `sanctioned_commodity.source` is `String(32)` per the
    schema, leaving 29 characters for the list name.
    """
    return f"{SOURCE_PREFIX}{list_name}"


def parse_csv(file: Path) -> list[str]:
    """Read the `keywords` column. Strip, dedupe (case-insensitive), drop blanks
    and entries shorter than MIN_KEYWORD_LEN. Preserves input order on the first
    occurrence.
    """
    # utf-8-sig strips a BOM if present — Excel-exported CSVs commonly include
    # one, which would otherwise corrupt the first header (e.g. "﻿keywords")
    # and defeat the column match below.
    with file.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return []
        # Case-insensitive column match — operators send "Keywords", "keyword", etc.
        col = None
        for name in reader.fieldnames:
            if name and name.strip().lower() in ("keywords", "keyword", "phrase", "phrases"):
                col = name
                break
        if col is None:
            raise ValueError(
                f"{file}: CSV must have a 'keywords' column "
                f"(got headers: {reader.fieldnames})"
            )
        seen: set[str] = set()
        out: list[str] = []
        for row in reader:
            raw = (row.get(col) or "").strip()
            if len(raw) < MIN_KEYWORD_LEN:
                continue
            key = raw.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(raw[:MAX_KEYWORD_LEN])
    return out


def _country_rules_for(manifest: KeywordList) -> list[dict[str, Any]]:
    """Translate manifest scope into CountryRule rows."""
    origin = manifest.origin_iso
    dest = manifest.destination_iso
    if not origin and not dest:
        # Global scope: one rule with both ISOs NULL — the screening filter
        # treats NULL as "any" via `IS NULL OR == ?`.
        return [
            {
                "origin_iso": None,
                "destination_iso": None,
                "restriction_type": manifest.restriction_type,
            }
        ]
    direction = (manifest.direction or "").strip().lower() or None
    if direction == "import_from" and origin:
        return [
            {
                "origin_iso": origin,
                "destination_iso": None,
                "restriction_type": manifest.restriction_type,
            }
        ]
    if direction == "export_to" and dest:
        return [
            {
                "origin_iso": None,
                "destination_iso": dest,
                "restriction_type": manifest.restriction_type,
            }
        ]
    if direction == "both" and (origin or dest):
        rules: list[dict[str, Any]] = []
        if origin:
            rules.append(
                {
                    "origin_iso": origin,
                    "destination_iso": None,
                    "restriction_type": manifest.restriction_type,
                }
            )
        if dest:
            rules.append(
                {
                    "origin_iso": None,
                    "destination_iso": dest,
                    "restriction_type": manifest.restriction_type,
                }
            )
        return rules
    # Direction unset but at least one ISO present: take both as a pair.
    return [
        {
            "origin_iso": origin,
            "destination_iso": dest,
            "restriction_type": manifest.restriction_type,
        }
    ]


def _record_id(src: str, phrase: str) -> str:
    """Content-addressed id for a keyword.

    Deliberately NOT positional: hashing the phrase means an edited keyword yields
    a new id, so the old keyword's current version is closed and the new phrase is
    inserted with a fresh embedding, while an unchanged keyword keeps a stable id
    (the bitemporal upsert then no-ops on it via content_hash).
    """
    h = hashlib.sha1(phrase.encode("utf-8")).hexdigest()[:12]
    return f"{src}-{h}"


def build_rows(list_name: str, phrases: list[str], manifest: KeywordList) -> list[dict[str, Any]]:
    """Project (list_name, phrase) pairs into the row shape `upsert_sanctioned_commodities` consumes."""
    src = source_key(list_name)
    rules = _country_rules_for(manifest)
    return [
        {
            "source_record_id": _record_id(src, p),
            "description": p,
            "hs_codes": [],  # semantic-only by default
            "restriction_type": manifest.restriction_type,
            "country_rules": rules,
        }
        for p in phrases
    ]


async def _ensure_materialization_enabled(
    db: AsyncSession, source: str, threshold: float
) -> None:
    """Upsert `sanctions_rule_config` so the post-ingest materializer fires for this source.

    Keyword lists are operator-authored and pointless without the rules layer turned
    on, so we enable materialization on first ingest (unlike pulled sanctions
    sources, which default to disabled to keep flipping them on a deliberate
    operator action).
    """
    stmt = insert(SanctionsRuleConfig).values(
        source=source,
        enabled=True,
        default_threshold=threshold,
        phrase_strategy="description_only",  # one phrase per row; no list splitting.
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["source"],
        set_={
            "enabled": True,
            "default_threshold": threshold,
            "phrase_strategy": "description_only",
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)


async def load_manifest(db: AsyncSession, list_name: str) -> KeywordList:
    row = (
        await db.execute(select(KeywordList).where(KeywordList.name == list_name))
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(
            f"keyword list {list_name!r} has no manifest row — create it via "
            f"PUT /api/v1/admin/keyword-lists/{list_name} before running."
        )
    if not row.source_file:
        raise ValueError(
            f"keyword list {list_name!r} has no source_file set — upload a CSV via "
            f"POST /api/v1/admin/keyword-lists/{list_name}/upload before running."
        )
    return row


async def _refresh_manifest_after_ingest(
    db: AsyncSession, list_name: str, row_count: int
) -> None:
    await db.execute(
        update(KeywordList)
        .where(KeywordList.name == list_name)
        .values(row_count=row_count, last_ingested_at=datetime.now(UTC))
    )
    await db.commit()


async def main_async(list_name: str) -> None:
    """Worker entry point. Re-loads the manifest fresh on each call (the operator
    may have updated scope/threshold between Run clicks)."""
    configure_logging()
    src = source_key(list_name)
    log.info("keyword_list.start", list_name=list_name, source=src)

    # Manifest load runs outside `with_run_logging` so a missing manifest error
    # surfaces as a 400 from the caller rather than a half-baked RefdataRun row.
    from app.db.session import SessionLocal

    async with SessionLocal() as setup_db:
        manifest = await load_manifest(setup_db, list_name)
        # Snapshot the manifest fields we need; the session below is a new one.
        snap = KeywordList(
            name=manifest.name,
            label=manifest.label,
            origin_iso=manifest.origin_iso,
            destination_iso=manifest.destination_iso,
            direction=manifest.direction,
            restriction_type=manifest.restriction_type,
            default_threshold=manifest.default_threshold,
            active=manifest.active,
            source_file=manifest.source_file,
        )

    csv_path = Path(snap.source_file)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"keyword list {list_name!r}: source_file {csv_path} does not exist"
        )

    phrases = parse_csv(csv_path)
    log.info("keyword_list.parsed", list_name=list_name, n=len(phrases))
    rows = build_rows(list_name, phrases, snap)

    async with with_run_logging(src, notes=f"keyword_list={list_name} file={csv_path}") as (db, run):
        # Orphan reconciliation is handled inside the bitemporal upsert: keywords
        # no longer present in the CSV have their current version closed (logical
        # delete), preserving history. No separate hard-delete pass.
        counts = await upsert_sanctioned_commodities(db, rows, source=src, run=run)
        await _ensure_materialization_enabled(db, src, float(snap.default_threshold))
        run.rows_upserted = counts["sanctioned"]
        run.notes = (
            (run.notes or "")
            + f" | rules={counts['rules']} | closed={counts.get('closed', 0)}"
        )

    async with SessionLocal() as final_db:
        await _refresh_manifest_after_ingest(final_db, list_name, len(rows))
