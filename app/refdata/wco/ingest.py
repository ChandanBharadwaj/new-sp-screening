"""Ingest the WCO international HS nomenclature into hs_code at levels 2/4/6.

The WCO publishes the HS nomenclature (currently HS 2022) as an XLSX file on
https://www.wcoomd.org/. Header layout varies between editions; we detect
columns by alias rather than position. WCO entries cover the international
6-digit codes only — country-specific tariff lines (HS 8-10 digit) live in
HTS / Schedule B and are not represented here.

USAGE:
    python -m app.refdata.wco.ingest --file ./data/taxonomy/wco_hs_2022.xlsx

Conflict policy: rows are upserted with ON CONFLICT DO NOTHING on the `code`
primary key. HTS / Schedule B (which carry US-specific titles and chapter
notes) win when they're loaded; WCO purely backfills international codes
that the US tables don't cover.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsCode
from app.refdata.common import (
    batches,
    lazy_embedder,
    mark_progress,
    update_tsv_for_table,
    with_run_logging,
)
from app.telemetry import log

CODE_KEYS = (
    "hscode", "hs code", "hs_code", "code", "product code", "productcode",
    "subheading", "heading", "tariff", "tariff code",
)
DESC_EN_KEYS = (
    "description", "description (en)", "description_en", "english",
    "english description", "label", "name", "title",
)
DESC_FR_KEYS = (
    "description (fr)", "description_fr", "french", "french description", "label_fr",
)


def _normalize_code(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float) and pd.isna(raw):
        return ""
    return re.sub(r"[^0-9]", "", str(raw))


def _pick(row: pd.Series, keys: tuple[str, ...]) -> str | None:
    for col in row.index:
        if str(col).strip().lower() in keys:
            v = row[col]
            if pd.isna(v):
                return None
            s = str(v).strip()
            return s or None
    return None


def _roll_up(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Build level-2/4/6 records keyed by code. Description columns are
    detected by header alias; English wins for `title`, French (if present)
    is appended to `description` for embedding."""
    by_code: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = _normalize_code(_pick(row, CODE_KEYS))
        desc_en = _pick(row, DESC_EN_KEYS) or ""
        desc_fr = _pick(row, DESC_FR_KEYS) or ""
        if not code or not desc_en:
            continue
        chapter = code[:2]
        heading = code[:4]
        subheading = code[:6]
        desc_combined = desc_en if not desc_fr else f"{desc_en} || {desc_fr}"

        for lvl, lvl_code in ((2, chapter), (4, heading), (6, subheading)):
            if len(lvl_code) < lvl:
                continue
            existing = by_code.get(lvl_code)
            if existing is None:
                by_code[lvl_code] = {
                    "code": lvl_code,
                    "level": lvl,
                    "chapter": chapter,
                    "parent_code": lvl_code[: lvl - 2] if lvl > 2 else None,
                    "title": desc_en[:512] or lvl_code,
                    "description": desc_combined,
                }
            else:
                if len(desc_combined) > len(existing["description"] or ""):
                    existing["description"] = desc_combined
                if not existing["title"]:
                    existing["title"] = desc_en[:512]
    return by_code


async def _upsert_rows(db: AsyncSession, rows: list[dict[str, Any]], run=None) -> int:
    if not rows:
        return 0
    embedder = lazy_embedder()
    n = 0
    for batch in batches(rows, 64):
        texts = [(r["title"] or "") + ". " + (r["description"] or "") for r in batch]
        vectors = embedder.encode_batch(texts)
        for r, v in zip(batch, vectors, strict=True):
            stmt = insert(HsCode).values(
                code=r["code"],
                level=r["level"],
                parent_code=r["parent_code"],
                chapter=r["chapter"],
                title=r["title"],
                description=r["description"],
                embedding=v.tolist(),
            )
            # HTS / Schedule B may have richer per-row data (chapter notes,
            # longer titles). Keep what's there; only fill gaps.
            stmt = stmt.on_conflict_do_nothing(index_elements=["code"])
            await db.execute(stmt)
            n += 1
        if run is not None:
            await mark_progress(db, run, n)
        else:
            await db.commit()
        log.info("wco.upsert_progress", rows=n, total=len(rows))
    return n


async def main_async(file: Path) -> None:
    if not file.exists():
        raise FileNotFoundError(f"WCO XLSX not found: {file}")
    log.info("wco.parsing", file=str(file))
    # Operator may have placed the relevant data on a non-default sheet.
    # Read the first sheet by default; if no descriptions detected, try others.
    df = pd.read_excel(file)
    rolled = _roll_up(df)
    if not rolled:
        # Fall back to all sheets concatenated; some WCO releases split by section.
        sheets = pd.read_excel(file, sheet_name=None)
        df = pd.concat(sheets.values(), ignore_index=True, sort=False)
        rolled = _roll_up(df)
    rows = sorted(rolled.values(), key=lambda r: (r["level"], r["code"]))
    log.info("wco.rolled_up", n_rows=len(rows))

    async with with_run_logging("WCO", notes=f"file={file}") as (db, run):
        n = await _upsert_rows(db, rows, run=run)
        await update_tsv_for_table(db, "hs_code", columns=("title", "description"))
        await db.commit()
        run.rows_upserted = n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--file",
        type=Path,
        default=Path("data/taxonomy/wco_hs_2022.xlsx"),
    )
    args = p.parse_args()
    asyncio.run(main_async(args.file))


if __name__ == "__main__":
    main()
