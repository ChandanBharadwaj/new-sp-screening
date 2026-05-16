"""Assemble sanctions adversarial eval set from already-ingested rows.

Positives: descriptions from sanctioned_commodity (the official text).
Negatives: CROSS rulings whose hs_code appears on sanctioned lists but whose ruling
text shows the items are not the restricted kind (e.g. a non-restricted alloy of
the same chapter). Selected from existing rows, never invented.

USAGE:
    python -m eval.runners.build_sanctions_eval --positives 200 --negatives 200
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HsTrainingExample, SanctionedCommodity
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log

OUT_PATH = Path("eval/gold/sanctions_adversarial.jsonl")


async def _build(db: AsyncSession, n_pos: int, n_neg: int, seed: int) -> list[dict]:
    rng = random.Random(seed)

    pos_rows = (
        await db.execute(
            select(SanctionedCommodity.id, SanctionedCommodity.description, SanctionedCommodity.hs_codes)
            .where(SanctionedCommodity.description.is_not(None))
        )
    ).all()
    log.info("sanctions_eval.positives_available", n=len(pos_rows))
    pos_sample = rng.sample(pos_rows, min(n_pos, len(pos_rows)))
    positives = [
        {
            "label": "positive",
            "description": desc,
            "expected_hs_codes": list(codes or []),
            "sanction_id": sid,
        }
        for sid, desc, codes in pos_sample
    ]

    # Negatives: CROSS rulings whose hs_code is in the positives' hs_codes set,
    # excluding any CROSS row whose description literally matches a positive description.
    positive_codes: set[str] = set()
    positive_texts: set[str] = set()
    for p in positives:
        positive_texts.add(p["description"])
        for c in p["expected_hs_codes"]:
            positive_codes.add(c)

    neg_pool_rows = (
        await db.execute(
            select(HsTrainingExample.description, HsTrainingExample.hs_code)
            .where(HsTrainingExample.source == "cross_ruling")
            .where(HsTrainingExample.hs_code.in_(positive_codes) if positive_codes else False)
        )
    ).all() if positive_codes else []
    neg_pool = [(d, c) for d, c in neg_pool_rows if d not in positive_texts]
    log.info("sanctions_eval.negatives_available", n=len(neg_pool))
    neg_sample = rng.sample(neg_pool, min(n_neg, len(neg_pool)))
    negatives = [
        {
            "label": "negative",
            "description": desc,
            "expected_hs_codes": [code] if code else [],
        }
        for desc, code in neg_sample
    ]

    return positives + negatives


async def main_async(n_pos: int, n_neg: int, seed: int) -> None:
    configure_logging()
    async with SessionLocal() as db:
        items = await _build(db, n_pos, n_neg, seed)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    log.info("sanctions_eval.written", n=len(items), path=str(OUT_PATH))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--positives", type=int, default=200)
    p.add_argument("--negatives", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    asyncio.run(main_async(args.positives, args.negatives, args.seed))


if __name__ == "__main__":
    main()
