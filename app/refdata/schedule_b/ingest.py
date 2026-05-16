"""Ingest US Census Schedule B export classifications as hs_training_example rows.

USAGE:
    python -m app.refdata.schedule_b.ingest --file ./data/schedule_b/schedule_b.csv

Get the CSV from https://www.census.gov/foreign-trade/schedules/b/. The file typically
has columns: SCHEDULE_B, COMMODITY_DESCRIPTION (column names vary by year). We accept
common aliases below.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsTrainingExample
from app.refdata.common import batches, lazy_embedder, update_tsv_for_table, with_run_logging
from app.telemetry import log

CODE_KEYS = ("schedule_b", "schedule_b_number", "code", "hs_code", "scheduleb")
DESC_KEYS = ("commodity_description", "description", "commodity", "long_description")


def _pick(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    norm = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}
    for k in keys:
        if k in norm and norm[k]:
            return norm[k].strip()
    return None


def _normalize_code(raw: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", raw or "")
    if len(digits) < 6:
        return None
    return digits[:6]  # truncate Schedule B 10-digit to HS subheading


async def _upsert_rows(db: AsyncSession, rows: list[tuple[str, str]]) -> int:
    embedder = lazy_embedder()
    n = 0
    for batch in batches(rows, 64):
        descriptions = [d for _, d in batch]
        vectors = embedder.encode_batch(descriptions)
        for (code, desc), v in zip(batch, vectors, strict=True):
            stmt = insert(HsTrainingExample).values(
                source="schedule_b",
                source_id=code,
                description=desc,
                hs_code=code,
                embedding=v.tolist(),
            )
            stmt = stmt.on_conflict_do_nothing()
            await db.execute(stmt)
            n += 1
        await db.commit()
        log.info("schedule_b.upsert_progress", rows=n)
    return n


async def main_async(file: Path) -> None:
    log.info("schedule_b.parsing", file=str(file))
    parsed: list[tuple[str, str]] = []
    with file.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code_raw = _pick(row, CODE_KEYS)
            desc = _pick(row, DESC_KEYS)
            if not code_raw or not desc:
                continue
            code = _normalize_code(code_raw)
            if not code:
                continue
            parsed.append((code, desc))
    log.info("schedule_b.parsed", n_rows=len(parsed))

    async with with_run_logging("ScheduleB", notes=f"file={file}") as (db, run):
        n = await _upsert_rows(db, parsed)
        await update_tsv_for_table(db, "hs_training_example", columns=("description",))
        await db.commit()
        run.rows_upserted = n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main_async(args.file))


if __name__ == "__main__":
    main()
