"""Promote analyst HS corrections from feedback_event into gold-set candidates.

USAGE:
    python -m eval.runners.sample_feedback_to_gold --since 2026-01-01

Writes eval/gold/feedback_pending.jsonl for secondary analyst review before merging
into the train/dev/test splits via app.refdata.gold.assemble.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db.models import FeedbackEvent, ScreeningResult, Shipment
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log

OUT_PATH = Path("eval/gold/feedback_pending.jsonl")


async def main_async(since: datetime | None) -> None:
    configure_logging()
    async with SessionLocal() as db:
        stmt = (
            select(FeedbackEvent, ScreeningResult, Shipment)
            .join(ScreeningResult, ScreeningResult.id == FeedbackEvent.result_id)
            .join(Shipment, Shipment.id == ScreeningResult.shipment_id)
            .where(FeedbackEvent.event_type == "hs_corrected")
        )
        if since:
            stmt = stmt.where(FeedbackEvent.created_at >= since)
        rows = (await db.execute(stmt)).all()
    items = []
    for fe, _res, ship in rows:
        after = (fe.after_value or {}).get("hs_code")
        if not after:
            continue
        items.append({"description": ship.commodity_text, "hs_code": after, "from_feedback_id": fe.id})
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    log.info("feedback_to_gold.written", n=len(items), path=str(OUT_PATH))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=str, default=None, help="ISO date, e.g. 2026-01-01")
    args = p.parse_args()
    since = datetime.fromisoformat(args.since) if args.since else None
    asyncio.run(main_async(since))


if __name__ == "__main__":
    main()
