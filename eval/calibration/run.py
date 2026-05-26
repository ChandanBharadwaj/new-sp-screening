"""One-command threshold calibration (item 3).

    python -m eval.calibration.run --gold eval/gold/splits/dev.jsonl

Pipeline: load held-out gold → generate synthetic labeled data (mixed with real) →
harvest confidence features once → sweep every post_hoc threshold + fit isotonic →
sweep retrieval thresholds by re-running the pipeline with injected overrides →
write recommendations into the policy tables (auto-apply) → emit a JSON report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.models.registry import load_models
from app.pipeline.policy import PolicySnapshot
from app.telemetry import configure_logging, log
from eval.calibration import apply as apply_mod
from eval.calibration import harvest as harvest_mod
from eval.calibration import sweep as sweep_mod
from eval.calibration.registry import REGISTRY, Threshold, by_kind
from eval.calibration.synthetic import build_synthetic


def _load_gold(path: Path) -> list[dict]:
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append(json.loads(line))
    return items


def _baseline_overrides() -> tuple[dict, dict]:
    """Current registry values as (thresholds, params) dicts for PolicySnapshot."""
    thresholds: dict[tuple[str, str], float] = {}
    params: dict[tuple[str, str], Any] = {}
    for t in REGISTRY:
        if t.store is None:
            continue
        table, a, b = t.store
        if table == "inference_threshold":
            thresholds[(a, b)] = t.current
        else:
            params[(a, b)] = t.current
    return thresholds, params


async def _retrieval_sweep(t: Threshold, examples: list[dict], models) -> dict:
    """Re-run the pipeline per grid value; best = max top1 accuracy."""
    base_th, base_pp = _baseline_overrides()
    table, a, b = t.store
    curve = []
    for v in t.sweep_values():
        th, pp = dict(base_th), dict(base_pp)
        if table == "inference_threshold":
            th[(a, b)] = v
        else:
            pp[(a, b)] = v
        override = PolicySnapshot.from_overrides(th, pp)
        rows = await harvest_mod.harvest(examples, models=models, policy_override=override)
        acc = sum(r["was_top1_correct"] for r in rows) / max(len(rows), 1)
        curve.append({"value": v, "top1_accuracy": round(acc, 4)})
    best = max(curve, key=lambda c: (c["top1_accuracy"], -abs(c["value"] - t.current)))
    return {"curve": curve, "recommended": best["value"], "best": best}


async def run_calibration(
    gold_path: Path,
    *,
    per_record: int = 1,
    coverage_floor: float = 0.5,
    retrieval_sample: int = 60,
    apply: bool = True,
    report_dir: Path = Path("artifacts/calibration"),
) -> dict:
    configure_logging()
    run_id = f"calib:{int(time.time())}"
    gold = _load_gold(gold_path)
    examples = build_synthetic(gold, per_record=per_record)
    log.info("calibration.start", run_id=run_id, gold=len(gold), examples=len(examples))

    models = load_models()
    harvested = await harvest_mod.harvest(examples, models=models)

    results: dict[str, Any] = {"run_id": run_id, "n_gold": len(gold), "n_examples": len(examples)}
    recommendations: list[dict] = []

    # post_hoc: sweep over harvested features, no re-run.
    post_hoc = {}
    for t in by_kind("post_hoc"):
        sw = sweep_mod.sweep_min_threshold(harvested, t.feature, t.sweep_values(), coverage_floor=coverage_floor)
        post_hoc[t.name] = sw
        recommendations.append({"store": t.store, "value": sw["recommended"],
                                "rationale": f"{run_id}: max accepted-precision @ coverage>={coverage_floor}"})
    results["post_hoc"] = post_hoc

    # isotonic calibration of top1_score → P(correct).
    results["isotonic"] = sweep_mod.fit_isotonic(
        [r["top1_score"] for r in harvested], [r["was_top1_correct"] for r in harvested]
    )

    # retrieval: re-run pipeline per grid value on a bounded synthetic sample.
    sample = examples[:retrieval_sample]
    retrieval = {}
    for t in by_kind("retrieval"):
        sw = await _retrieval_sweep(t, sample, models)
        retrieval[t.name] = sw
        recommendations.append({"store": t.store, "value": sw["recommended"],
                                "rationale": f"{run_id}: max top1 accuracy on {len(sample)} synthetic queries"})
    results["retrieval"] = retrieval

    # reported_only: structural ints (config/env), reported but never auto-applied.
    results["reported_only"] = {
        t.name: {"current": t.current, "note": "config/env tunable — change app/config.py, not a policy table"}
        for t in by_kind("reported_only")
    }

    results["recommendations"] = [
        {"name": t.name, "store": t.store, "current": t.current}
        for t in REGISTRY if t.store is not None
    ]

    if apply:
        async with SessionLocal() as db:
            results["applied"] = await apply_mod.apply_all(db, recommendations, calibrated_from=run_id)
    else:
        results["applied"] = 0

    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(results, indent=2))
    log.info("calibration.done", run_id=run_id, applied=results["applied"])
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", type=Path, default=Path("eval/gold/splits/dev.jsonl"))
    p.add_argument("--per-record", type=int, default=1)
    p.add_argument("--coverage-floor", type=float, default=0.5)
    p.add_argument("--retrieval-sample", type=int, default=60)
    p.add_argument("--no-apply", action="store_true", help="dry-run: do not write to policy tables")
    p.add_argument("--report-dir", type=Path, default=Path("artifacts/calibration"))
    args = p.parse_args()
    res = asyncio.run(
        run_calibration(
            args.gold, per_record=args.per_record, coverage_floor=args.coverage_floor,
            retrieval_sample=args.retrieval_sample, apply=not args.no_apply, report_dir=args.report_dir,
        )
    )
    print(json.dumps({k: v for k, v in res.items() if k in ("run_id", "n_examples", "applied", "isotonic")}, indent=2))


if __name__ == "__main__":
    main()
