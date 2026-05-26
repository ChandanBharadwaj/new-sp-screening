from __future__ import annotations

import numpy as np

from eval.calibration.sweep import (
    expected_calibration_error,
    fit_isotonic,
    sweep_min_threshold,
)


def _records():
    # High top1_score → correct; low → wrong. A min-threshold should accept the
    # high-score (correct) ones and abstain on the low-score (wrong) ones.
    rows = []
    for s in [0.9, 0.85, 0.8, 0.75]:
        rows.append({"top1_score": s, "was_top1_correct": True})
    for s in [0.2, 0.25, 0.3, 0.35]:
        rows.append({"top1_score": s, "was_top1_correct": False})
    return rows


def test_sweep_recommends_separating_threshold() -> None:
    sw = sweep_min_threshold(_records(), "top1_score",
                             [round(0.1 * i, 2) for i in range(1, 10)], coverage_floor=0.3)
    # Best precision is achievable at a cut between the two clusters (~0.4-0.75).
    assert sw["best"]["precision"] == 1.0
    assert 0.4 <= sw["recommended"] <= 0.75
    # Curve covers every swept value.
    assert len(sw["curve"]) == 9


def test_coverage_floor_forces_more_coverage() -> None:
    # With a high coverage floor we cannot abstain on much, so precision must drop.
    sw = sweep_min_threshold(_records(), "top1_score",
                             [round(0.1 * i, 2) for i in range(1, 10)], coverage_floor=0.99)
    assert sw["best"]["coverage"] >= 0.99


def test_ece_perfect_calibration_is_zero() -> None:
    probs = np.array([0.0, 0.0, 1.0, 1.0])
    labels = np.array([0.0, 0.0, 1.0, 1.0])
    assert expected_calibration_error(probs, labels, n_bins=2) == 0.0


def test_isotonic_improves_or_matches_calibration() -> None:
    scores = [0.9, 0.85, 0.8, 0.75, 0.2, 0.25, 0.3, 0.35]
    labels = [True, True, True, True, False, False, False, False]
    res = fit_isotonic(scores, labels)
    assert res["n"] == 8
    assert res["ece_calibrated"] <= res["ece_uncalibrated"] + 1e-9
