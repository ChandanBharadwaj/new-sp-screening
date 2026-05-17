"""RRF blender in app/pipeline/retrieval/union.py — pure unit test, no DB.

The whole point of RRF is rank-order invariance to score scale; we test that
property explicitly so a future regression to score-based blending (where
multiplying a source's scores by a constant would change the output order)
fails this test loudly.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.pipeline.retrieval.union import merge


@pytest.fixture(autouse=True)
def force_rrf(monkeypatch):
    monkeypatch.setattr(settings, "fusion_mode", "rrf")
    monkeypatch.setattr(settings, "rrf_k", 60)


def _list(*codes: str, score_field: str = "dense_similarity") -> list[dict]:
    return [{"hs_code": c, score_field: 1.0} for c in codes]


def test_rrf_score_is_added_in_rrf_mode() -> None:
    dense = _list("854231", "854232")
    sparse = _list("854231", score_field="sparse_score")
    out = {c["hs_code"]: c for c in merge(dense, sparse)}

    # 854231 appears at rank 1 in dense and rank 1 in sparse -> 2/(60+1) ≈ 0.0328.
    assert out["854231"]["rrf_score"] == pytest.approx(2.0 / 61.0, rel=1e-6)
    # 854232 appears at rank 2 in dense only -> 1/(60+2) ≈ 0.0161.
    assert out["854232"]["rrf_score"] == pytest.approx(1.0 / 62.0, rel=1e-6)


def test_rrf_is_scale_invariant() -> None:
    """Multiplying one source's scores by 1000 must not change the RRF order."""
    a = _list("X", "Y", "Z")
    b = _list("Y", "X", score_field="sparse_score")

    out1 = {c["hs_code"]: c["rrf_score"] for c in merge(a, b)}
    # Scale b's score field by 1000 — RRF uses position, not value.
    b_scaled = [dict(d, sparse_score=1000.0) for d in b]
    out2 = {c["hs_code"]: c["rrf_score"] for c in merge(a, b_scaled)}
    assert out1 == out2


def test_max_mode_does_not_emit_rrf_score(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fusion_mode", "max")
    out = {c["hs_code"]: c for c in merge(_list("A"), _list("B"))}
    # `rrf_score` is initialized to 0.0 in the template, but never incremented in max mode.
    assert out["A"]["rrf_score"] == 0.0
    assert out["B"]["rrf_score"] == 0.0
    # Per-source max-blend still populates the legacy field.
    assert out["A"]["dense_similarity"] == 1.0


def test_meta_fields_preserved() -> None:
    a = [{"hs_code": "854231", "level": 6, "chapter": "85", "title": "T", "description": "D"}]
    b = [{"hs_code": "854231", "sparse_score": 1.0}]
    out = {c["hs_code"]: c for c in merge(a, b)}
    assert out["854231"]["title"] == "T"
    assert out["854231"]["level"] == 6
    assert out["854231"]["chapter"] == "85"
