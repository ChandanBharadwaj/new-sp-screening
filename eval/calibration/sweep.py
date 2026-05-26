"""Threshold sweeping + isotonic calibration math (item 3).

Pure functions over harvested per-query records so they are unit-testable without a
DB or models. A harvested record is a dict with at least the feature keys used by the
registry (top1_score, gap, chapter_consensus, dense, cross_encoder) and a boolean
`was_top1_correct`.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def sweep_min_threshold(
    records: list[dict],
    feature: str,
    values: list[float],
    *,
    coverage_floor: float = 0.5,
) -> dict[str, Any]:
    """Sweep a 'minimum' gate: a query is ACCEPTED when record[feature] >= value.

    For each candidate value compute accepted-precision (fraction of accepted queries
    whose top1 was correct) and coverage (fraction accepted). Recommend the value that
    maximizes accepted-precision subject to coverage >= coverage_floor; if no value
    meets the floor, fall back to the one with the highest coverage.
    """
    feats = np.array([float(r.get(feature, 0.0)) for r in records], dtype=float)
    correct = np.array([bool(r.get("was_top1_correct")) for r in records], dtype=bool)
    n = len(records)
    curve = []
    for v in values:
        accepted = feats >= v
        acc_n = int(accepted.sum())
        coverage = acc_n / n if n else 0.0
        precision = float(correct[accepted].mean()) if acc_n else 0.0
        curve.append({"value": v, "precision": round(precision, 4),
                      "coverage": round(coverage, 4), "accepted_n": acc_n})

    eligible = [c for c in curve if c["coverage"] >= coverage_floor]
    pool = eligible or curve
    # Max precision; tie-break on higher coverage, then lower value (less aggressive).
    best = max(pool, key=lambda c: (c["precision"], c["coverage"], -c["value"]))
    return {"feature": feature, "coverage_floor": coverage_floor, "curve": curve,
            "recommended": best["value"], "best": best}


def brier_score(probs: np.ndarray, labels: np.ndarray) -> float:
    return float(np.mean((probs - labels) ** 2))


def expected_calibration_error(probs: np.ndarray, labels: np.ndarray, n_bins: int = 15) -> float:
    """ECE with equal-mass bins (quantile binning)."""
    n = len(probs)
    if n == 0:
        return 0.0
    order = np.argsort(probs)
    probs, labels = probs[order], labels[order]
    bins = np.array_split(np.arange(n), n_bins)
    ece = 0.0
    for b in bins:
        if len(b) == 0:
            continue
        conf = probs[b].mean()
        acc = labels[b].mean()
        ece += (len(b) / n) * abs(acc - conf)
    return float(ece)


def fit_isotonic(scores: list[float], labels: list[bool], *, target_precision: float = 0.95) -> dict[str, Any]:
    """Fit P(top1 correct) = isotonic(score); report ECE/Brier vs the raw score and
    the calibrated-probability cutoff that first reaches `target_precision`.
    """
    from sklearn.isotonic import IsotonicRegression

    x = np.asarray(scores, dtype=float)
    y = np.asarray([1.0 if v else 0.0 for v in labels], dtype=float)
    if len(x) == 0:
        return {"n": 0}
    iso = IsotonicRegression(out_of_bounds="clip")
    cal = iso.fit_transform(x, y)

    # Cutoff: smallest calibrated prob whose accept-set (>= cutoff) hits target precision.
    cutoff = None
    order = np.argsort(cal)
    cal_sorted, y_sorted = cal[order], y[order]
    for i in range(len(cal_sorted)):
        accepted = y_sorted[i:]
        if len(accepted) and accepted.mean() >= target_precision:
            cutoff = float(cal_sorted[i])
            break

    return {
        "n": int(len(x)),
        "ece_uncalibrated": round(expected_calibration_error(x, y), 4),
        "ece_calibrated": round(expected_calibration_error(cal, y), 4),
        "brier_uncalibrated": round(brier_score(x, y), 4),
        "brier_calibrated": round(brier_score(cal, y), 4),
        "target_precision": target_precision,
        "calibrated_prob_cutoff": cutoff,
    }
