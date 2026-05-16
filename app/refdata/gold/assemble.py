"""Assemble the eval gold set from already-imported reference data.

Reads (description, hs_code) rows from hs_training_example, stratifies by 2-digit
chapter, samples up to --per-chapter rows per chapter, splits 70/15/15 by chapter
into eval/gold/splits/{train,dev,test}.jsonl. No synthesis.

USAGE:
    python -m app.refdata.gold.assemble --target 1200 --per-chapter 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from app.db.models import HsTrainingExample
from app.refdata.common import with_run_logging
from app.telemetry import configure_logging, log

SPLITS_DIR = Path("eval/gold/splits")
DEFAULT_SOURCES = ("cross_ruling", "schedule_b")


def _chapter_of(code: str) -> str:
    return (code or "")[:2]


async def main_async(
    target: int,
    per_chapter: int,
    sources: list[str],
    train_frac: float,
    dev_frac: float,
    seed: int,
) -> None:
    configure_logging()
    rng = random.Random(seed)

    async with with_run_logging("GoldAssembly", notes=f"target={target}") as (db, run):
        stmt = select(HsTrainingExample.description, HsTrainingExample.hs_code).where(
            HsTrainingExample.source.in_(sources),
            HsTrainingExample.hs_code.is_not(None),
        )
        rows = (await db.execute(stmt)).all()
        log.info("gold.fetched", n_rows=len(rows), sources=sources)
        if not rows:
            log.warning("gold.no_data — ingest CROSS/Schedule B first")
            run.rows_upserted = 0
            return

        by_chapter: dict[str, list[dict]] = defaultdict(list)
        for desc, code in rows:
            chap = _chapter_of(code)
            if not chap:
                continue
            by_chapter[chap].append({"description": desc, "hs_code": code})

        # Sample up to per_chapter from each chapter; cap at target overall.
        sampled: list[dict] = []
        for chap, items in by_chapter.items():
            rng.shuffle(items)
            sampled.extend(items[:per_chapter])
        rng.shuffle(sampled)
        if len(sampled) > target:
            sampled = sampled[:target]

        # Per-chapter 70/15/15 to avoid leakage.
        chapter_buckets: dict[str, list[dict]] = defaultdict(list)
        for it in sampled:
            chapter_buckets[_chapter_of(it["hs_code"])].append(it)

        train: list[dict] = []
        dev: list[dict] = []
        test: list[dict] = []
        for chap, items in chapter_buckets.items():
            rng.shuffle(items)
            n = len(items)
            n_train = int(n * train_frac)
            n_dev = int(n * dev_frac)
            train.extend(items[:n_train])
            dev.extend(items[n_train : n_train + n_dev])
            test.extend(items[n_train + n_dev :])

        SPLITS_DIR.mkdir(parents=True, exist_ok=True)
        for name, split in (("train", train), ("dev", dev), ("test", test)):
            path = SPLITS_DIR / f"{name}.jsonl"
            with path.open("w") as f:
                for it in split:
                    f.write(json.dumps(it) + "\n")
            log.info("gold.split_written", name=name, n=len(split), path=str(path))

        # Per-chapter counts to stdout for transparency.
        print("\nPer-chapter counts (total / train / dev / test):")
        for chap in sorted(chapter_buckets.keys()):
            items = chapter_buckets[chap]
            n = len(items)
            print(f"  {chap}: {n}  ({int(n * train_frac)} / {int(n * dev_frac)} / {n - int(n * train_frac) - int(n * dev_frac)})")

        run.rows_upserted = len(sampled)
        run.notes = (run.notes or "") + f" | sampled={len(sampled)} chapters={len(chapter_buckets)}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=1200)
    p.add_argument("--per-chapter", type=int, default=30)
    p.add_argument("--sources", type=str, default=",".join(DEFAULT_SOURCES))
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--dev-frac", type=float, default=0.15)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    asyncio.run(
        main_async(args.target, args.per_chapter, sources, args.train_frac, args.dev_frac, args.seed)
    )


if __name__ == "__main__":
    main()
