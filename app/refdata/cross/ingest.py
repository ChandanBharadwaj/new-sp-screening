"""Ingest CROSS rulings into hs_training_example.

Two input modes:
1. Curated JSONL committed to the repo (default Phase 0/1 path):
       eval/gold/cross_curated.jsonl with rows: {"description": "...", "hs_code": "...", "ruling_id": "..."}
2. Cached HTML from app.refdata.cross.scraper, parsed into the same shape.

USAGE:
    python -m app.refdata.cross.ingest                          # uses curated jsonl
    python -m app.refdata.cross.ingest --html-dir data/cross_raw
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsTrainingExample
from app.refdata.common import batches, lazy_embedder, update_tsv_for_table, with_run_logging
from app.telemetry import log

CURATED_PATH = Path("eval/gold/cross_curated.jsonl")
HS_RE = re.compile(r"\b(\d{4}\.\d{2}|\d{6,10})\b")


def _normalize_code(raw: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", raw or "")
    if len(digits) < 6:
        return None
    return digits[:6]


def _from_curated(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("cross.curated_missing", path=str(path))
        return []
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def _from_html_dir(directory: Path) -> list[dict]:
    items = []
    for f in directory.glob("*.html"):
        try:
            soup = BeautifulSoup(f.read_text(encoding="utf-8", errors="replace"), "lxml")
            text = soup.get_text(" ", strip=True)
            m = HS_RE.search(text)
            if not m:
                continue
            code = _normalize_code(m.group(1))
            if not code:
                continue
            items.append({"description": text[:1000], "hs_code": code, "ruling_id": f.stem})
        except Exception as e:
            log.warning("cross.html_parse_failed", file=str(f), error=str(e))
    return items


async def _upsert(db: AsyncSession, items: list[dict]) -> int:
    if not items:
        return 0
    embedder = lazy_embedder()
    n = 0
    for batch in batches(items, 64):
        descs = [it["description"] for it in batch]
        vectors = embedder.encode_batch(descs)
        for it, v in zip(batch, vectors, strict=True):
            stmt = insert(HsTrainingExample).values(
                source="cross_ruling",
                source_id=it.get("ruling_id"),
                description=it["description"],
                hs_code=_normalize_code(it["hs_code"]),
                embedding=v.tolist(),
            )
            stmt = stmt.on_conflict_do_nothing()
            await db.execute(stmt)
            n += 1
        await db.commit()
        log.info("cross.upsert_progress", rows=n)
    return n


async def main_async(html_dir: Path | None) -> None:
    items = _from_curated(CURATED_PATH)
    if html_dir:
        items.extend(_from_html_dir(html_dir))
    log.info("cross.parsed", n=len(items))
    async with with_run_logging("CROSS", notes=f"curated={CURATED_PATH.exists()} html_dir={html_dir}") as (db, run):
        n = await _upsert(db, items)
        await update_tsv_for_table(db, "hs_training_example", columns=("description",))
        await db.commit()
        run.rows_upserted = n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--html-dir", type=Path, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.html_dir))


if __name__ == "__main__":
    main()
