from __future__ import annotations

from app.pipeline.policy import PolicySnapshot


def test_from_overrides_returns_injected_values() -> None:
    snap = PolicySnapshot.from_overrides(
        thresholds={("hs_classify", "min_top1"): 0.55},
        params={("decompose", "conf_gate"): 0.7},
    )
    assert snap.threshold("hs_classify", "min_top1", 0.45) == 0.55
    assert snap.param("decompose", "conf_gate", 0.5) == 0.7
    # Unset keys fall back to the caller default.
    assert snap.threshold("hs_classify", "min_gap", 0.05) == 0.05
    assert snap.version == "override"


def test_from_overrides_empty_uses_defaults() -> None:
    snap = PolicySnapshot.from_overrides()
    assert snap.param("gliner", "min_score", 0.4) == 0.4
