"""Ingest the US Harmonized Tariff Schedule into hs_code at levels 2/4/6.

USAGE:
    python -m app.refdata.hts.ingest --year 2025
    python -m app.refdata.hts.ingest --file /path/to/htsdata.json

The USITC publishes htsdata.json yearly at https://hts.usitc.gov/. Each row is a leaf-ish
HTS line; we roll them up into chapter / heading / subheading rows by truncation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsCode
from app.refdata.common import batches, lazy_embedder, update_tsv_for_table, with_run_logging
from app.telemetry import log

HTS_URL_TEMPLATE = "https://hts.usitc.gov/reststop/exportList?from=0100000000&to=9999999999&format=JSON&styles=false"


async def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        log.info("hts.cache_hit", path=str(dest))
        return dest
    async with httpx.AsyncClient(timeout=120) as client:
        log.info("hts.downloading", url=url)
        r = await client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def _normalize_code(raw: str) -> str:
    return re.sub(r"[^0-9]", "", raw or "")


def _roll_up(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate raw HTS rows into level-2/4/6 records."""
    by_code: dict[str, dict[str, Any]] = {}
    chapter_descriptions: dict[str, str] = {}

    for it in items:
        code = _normalize_code(it.get("htsno") or "")
        desc = (it.get("description") or "").strip()
        if not code:
            # often these are chapter / heading rollup rows; try to capture chapter notes
            indent = it.get("indent")
            if indent in ("0", 0) and desc:
                # heuristic: standalone "Section" rows have no code
                pass
            continue

        chapter = code[:2]
        heading = code[:4]
        subheading = code[:6]

        if chapter not in chapter_descriptions:
            chapter_descriptions[chapter] = ""

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
                    "title": desc[:512] if lvl != 6 else (desc[:512] or lvl_code),
                    "description": desc,
                }
            else:
                # Keep the longest title we've seen; concatenate descriptions.
                if len(desc) > len(existing["description"] or ""):
                    existing["description"] = desc
                if not existing["title"] or len(desc) < len(existing["title"]):
                    existing["title"] = desc[:512] or existing["title"]

    return by_code


async def _upsert_rows(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
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
            stmt = stmt.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "level": stmt.excluded.level,
                    "parent_code": stmt.excluded.parent_code,
                    "chapter": stmt.excluded.chapter,
                    "title": stmt.excluded.title,
                    "description": stmt.excluded.description,
                    "embedding": stmt.excluded.embedding,
                    "updated_at": text("now()"),
                },
            )
            await db.execute(stmt)
            n += 1
        await db.commit()
        log.info("hts.upsert_progress", rows=n, total=len(rows))
    return n


async def main_async(year: int | None, file: Path | None) -> None:
    if file is None:
        cache_dir = Path("data/hts")
        file = cache_dir / f"htsdata_{year or 'latest'}.json"
        await _download(HTS_URL_TEMPLATE, file)

    log.info("hts.parsing", file=str(file))
    raw = json.loads(file.read_text())
    if isinstance(raw, dict) and "results" in raw:
        items = raw["results"]
    else:
        items = raw
    rolled = _roll_up(items)
    rows = sorted(rolled.values(), key=lambda r: (r["level"], r["code"]))
    log.info("hts.rolled_up", n_rows=len(rows))

    async with with_run_logging("HTS", notes=f"file={file}") as (db, run):
        n = await _upsert_rows(db, rows)
        await update_tsv_for_table(db, "hs_code", columns=("title", "description"))
        await db.commit()
        run.rows_upserted = n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--file", type=Path, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.year, args.file))


if __name__ == "__main__":
    main()
