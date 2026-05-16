"""Evaluate semantic rules against labeled shipments.

INPUT FORMAT (eval/gold/rule_eval.jsonl, operator-prepared):
    {"commodity_text": "...", "expected_rule_ids": [42, 17]}

Until operators label real shipment→rule expectations, no eval input ships in the repo
(per the no-synthesis constraint).

USAGE:
    python -m eval.runners.run_rule_eval --in eval/gold/rule_eval.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.models.registry import load_models
from app.pipeline.orchestrator import run_screen
from app.telemetry import configure_logging, log


async def main_async(in_path: Path, threshold_delta: float) -> None:
    configure_logging()
    if not in_path.exists():
        log.error("rule_eval.no_input", path=str(in_path))
        return
    items = [json.loads(line) for line in in_path.read_text().splitlines() if line.strip()]
    models = load_models()

    n_recall_num = n_recall_den = 0
    n_precision_num = n_precision_den = 0
    async with SessionLocal() as db:
        for rec in items:
            payload = await run_screen(db=db, models=models, commodity_text=rec["commodity_text"])
            fired = {
                int(m["rule_id"])
                for m in payload.get("rule_matches", [])
                if m["delta_above_threshold"] >= threshold_delta and m["conditions_satisfied"]
            }
            expected = set(int(x) for x in rec.get("expected_rule_ids", []))
            n_recall_num += len(fired & expected)
            n_recall_den += len(expected)
            n_precision_num += len(fired & expected)
            n_precision_den += len(fired)

    recall = n_recall_num / n_recall_den if n_recall_den else 0.0
    precision = n_precision_num / n_precision_den if n_precision_den else 0.0
    print(json.dumps({"recall": recall, "precision": precision, "threshold_delta": threshold_delta}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, default=Path("eval/gold/rule_eval.jsonl"))
    p.add_argument("--threshold-delta", type=float, default=0.0)
    args = p.parse_args()
    asyncio.run(main_async(args.in_path, args.threshold_delta))


if __name__ == "__main__":
    main()
