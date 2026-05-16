"""CI gate: fail if the eval report doesn't clear thresholds (with a tolerance band).

USAGE:
    python -m eval.ci.compare --report eval/reports/run.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

THRESHOLDS = Path("eval/ci/thresholds.yaml")
TOLERANCE = {  # absolute slack vs threshold
    "top1_subheading": -0.005,
    "top3_subheading": -0.005,
    "top1_chapter": -0.005,
    "mrr": -0.005,
    "p95_ms": 50,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--baseline", type=Path, default=None)
    args = p.parse_args()

    thresholds = yaml.safe_load(THRESHOLDS.read_text())
    report = json.loads(args.report.read_text())
    metrics = report["metrics"]
    p95 = report["latency"]["p95"]

    failures: list[str] = []

    def check_min(key: str, actual: float) -> None:
        thresh = thresholds[key]
        floor = thresh + TOLERANCE.get(key, 0)
        status = "OK" if actual >= floor else "FAIL"
        print(f"{status:4s} {key}: actual={actual:.4f} threshold={thresh:.4f} floor={floor:.4f}")
        if status == "FAIL":
            failures.append(key)

    def check_max(key: str, actual: float) -> None:
        thresh = thresholds[key]
        ceiling = thresh + TOLERANCE.get(key, 0)
        status = "OK" if actual <= ceiling else "FAIL"
        print(f"{status:4s} {key}: actual={actual:.1f}ms threshold={thresh}ms ceiling={ceiling}ms")
        if status == "FAIL":
            failures.append(key)

    check_min("top1_subheading", metrics["top1_subheading"])
    check_min("top3_subheading", metrics["top3_subheading"])
    check_min("top1_chapter", metrics["top1_chapter"])
    check_min("mrr", metrics["mrr"])
    check_max("p95_ms", p95)

    if failures:
        print(f"\nEval gate FAILED on: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nEval gate PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
