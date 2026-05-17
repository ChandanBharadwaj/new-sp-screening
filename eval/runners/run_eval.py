"""Run the eval harness.

USAGE:
    python -m eval.runners.run_eval --classifier baseline_noop --split test
    python -m eval.runners.run_eval --classifier pipeline --split test --report eval/reports/run.json
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import insert as sa_insert

from app.db.models import EvalRun
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log
from eval.metrics import confusion, latency, ranking

GOLD_DIR = Path("eval/gold/splits")

LogFn = Callable[[str], Awaitable[None] | None]


def _load_split(split: str) -> list[dict]:
    f = GOLD_DIR / f"{split}.jsonl"
    if not f.exists():
        raise FileNotFoundError(f"missing gold split: {f}")
    items = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(json.loads(line))
    return items


def _load_classifier(name: str):
    mod_path = f"eval.runners.{name}" if "." not in name else name
    if name == "pipeline":
        mod_path = "eval.runners.pipeline_classifier"
    mod = importlib.import_module(mod_path)
    return mod.Classifier()


async def _persist_run(report: dict) -> int | None:
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                sa_insert(EvalRun)
                .values(
                    classifier=report["classifier"],
                    split=report["split"],
                    top1_subheading=report["metrics"]["top1_subheading"],
                    top3_subheading=report["metrics"]["top3_subheading"],
                    top1_chapter=report["metrics"]["top1_chapter"],
                    mrr=report["metrics"]["mrr"],
                    p50_ms=report["latency"]["p50"],
                    p95_ms=report["latency"]["p95"],
                    p99_ms=report["latency"]["p99"],
                    n_examples=report["n_examples"],
                    report_json=report,
                )
                .returning(EvalRun.id)
            )
            new_id = result.scalar_one()
            await db.commit()
            log.info("eval.run_persisted", eval_run_id=new_id)
            return int(new_id)
    except Exception as e:
        log.warning("eval.run_persist_failed", error=str(e))
        return None


async def _emit(log_fn: LogFn | None, msg: str) -> None:
    if log_fn is None:
        return
    res = log_fn(msg)
    if asyncio.iscoroutine(res):
        await res


async def run(
    classifier: str,
    split: str,
    limit: int | None = None,
    report_path: str | None = None,
    log_fn: LogFn | None = None,
) -> dict[str, Any]:
    """Reusable entrypoint — CLI and the arq worker both call this.

    Returns the report dict plus `eval_run_id` (None if persistence failed).
    """
    configure_logging()
    items = _load_split(split)
    if limit:
        items = items[:limit]
    log.info("eval.start", classifier=classifier, split=split, n=len(items))
    await _emit(log_fn, f"Loaded {len(items)} gold items from split={split}")

    clf = _load_classifier(classifier)
    await _emit(log_fn, f"Loaded classifier '{classifier}'")

    predictions: list[list[str]] = []
    gold: list[str] = []
    latencies: list[float] = []
    for idx, rec in enumerate(items):
        t0 = time.perf_counter()
        preds = await clf.classify(rec["description"])
        latencies.append((time.perf_counter() - t0) * 1000)
        predictions.append(preds or [""])
        gold.append(rec["hs_code"])
        if (idx + 1) % 25 == 0:
            log.info("eval.progress", done=idx + 1, total=len(items))
            await _emit(log_fn, f"Classified {idx + 1}/{len(items)}")

    metrics = {
        "top1_subheading": ranking.top_k_subheading(predictions, gold, 1),
        "top3_subheading": ranking.top_k_subheading(predictions, gold, 3),
        "top5_subheading": ranking.top_k_subheading(predictions, gold, 5),
        "top1_heading": ranking.top_k_heading(predictions, gold, 1),
        "top1_chapter": ranking.top_k_chapter(predictions, gold, 1),
        "mrr": ranking.mean_reciprocal_rank(predictions, gold),
    }
    lat = latency.percentiles(latencies)
    conf_matrix = confusion.chapter_confusion(predictions, gold)
    report = {
        "classifier": classifier,
        "split": split,
        "n_examples": len(items),
        "metrics": metrics,
        "latency": lat,
        "confusion": {
            "matrix": conf_matrix,
            "hardest_pairs": confusion.hardest_pairs(conf_matrix),
        },
    }
    log.info(
        "eval.done",
        classifier=classifier,
        split=split,
        top1_sub=metrics["top1_subheading"],
        top3_sub=metrics["top3_subheading"],
        top1_chap=metrics["top1_chapter"],
        p95_ms=lat["p95"],
    )
    await _emit(
        log_fn,
        f"Done — top1_sub={metrics['top1_subheading']:.3f} "
        f"top3_sub={metrics['top3_subheading']:.3f} "
        f"top1_chap={metrics['top1_chapter']:.3f} "
        f"p95={lat['p95']:.0f}ms",
    )

    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(report, indent=2))
        log.info("eval.report_written", path=report_path)

    eval_run_id = await _persist_run(report)
    report["eval_run_id"] = eval_run_id
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--classifier", required=True, help="baseline_noop | pipeline")
    p.add_argument("--split", default="test", choices=["train", "dev", "test"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--report", type=str, default=None)
    args = p.parse_args()
    asyncio.run(
        run(
            classifier=args.classifier,
            split=args.split,
            limit=args.limit,
            report_path=args.report,
        )
    )


if __name__ == "__main__":
    main()
