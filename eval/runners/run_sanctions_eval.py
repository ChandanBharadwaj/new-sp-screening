"""Evaluate the sanctions matching pipeline against the adversarial set.

Measures positive recall (positives that surface ≥1 sanction match) and negative
FP rate (negatives that surface ≥1 sanction match).

USAGE:
    python -m eval.runners.run_sanctions_eval --in eval/gold/sanctions_adversarial.jsonl
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


async def main_async(in_path: Path, threshold: float) -> None:
    configure_logging()
    items = [json.loads(line) for line in in_path.read_text().splitlines() if line.strip()]
    models = load_models()

    tp = fn = fp = tn = 0
    async with SessionLocal() as db:
        for rec in items:
            payload = await run_screen(
                db=db, models=models, commodity_text=rec["description"]
            )
            hits = [m for m in payload.get("sanction_matches", []) if m.get("similarity", 0.0) >= threshold]
            has_hit = len(hits) > 0
            if rec["label"] == "positive":
                if has_hit:
                    tp += 1
                else:
                    fn += 1
            else:
                if has_hit:
                    fp += 1
                else:
                    tn += 1
    total_pos = tp + fn
    total_neg = fp + tn
    recall = tp / total_pos if total_pos else 0.0
    fp_rate = fp / total_neg if total_neg else 0.0
    log.info(
        "sanctions_eval.done",
        threshold=threshold,
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        recall=recall,
        fp_rate=fp_rate,
    )
    print(json.dumps({"threshold": threshold, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                      "recall": recall, "fp_rate": fp_rate}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, default=Path("eval/gold/sanctions_adversarial.jsonl"))
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args()
    asyncio.run(main_async(args.in_path, args.threshold))


if __name__ == "__main__":
    main()
