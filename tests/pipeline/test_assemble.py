"""Assemble tests — confirm the new fields land in the payload."""
from uuid import uuid4

from app.pipeline.assemble import build


def _cand(code: str, score: float) -> dict:
    return {
        "hs_code": code,
        "level": 6,
        "chapter": code[:2],
        "title": "x",
        "score": score,
        "score_components": {"dense": 0.5},
    }


def test_build_includes_abstention_and_versions() -> None:
    payload = build(
        shipment_id=uuid4(),
        candidates=[_cand("720839", 0.3), _cand("720840", 0.25)],
        entities={"material": ["steel"]},
        confidence={"top1_score": 0.3},
        latency={"total": 100},
        abstention={"abstained": True, "reason": "low_top1", "fallback_level": 2},
        fallback={"hs_code": "72", "level": "chapter", "title": "x", "score": 0.3, "score_components": {}},
        multi_commodity=None,
        versions={"engine": "0.1.0", "ltr_hash": "sha256:abc"},
    )

    hs = payload["hs_classification"]
    assert hs["abstained"] is True
    assert hs["abstain_reason"] == "low_top1"
    assert hs["fallback_level"] == 2
    assert hs["fallback_candidate"]["hs_code"] == "72"
    assert payload["versions"] == {"engine": "0.1.0", "ltr_hash": "sha256:abc"}


def test_build_includes_multi_commodity() -> None:
    payload = build(
        shipment_id=uuid4(),
        candidates=[_cand("720839", 0.9)],
        entities={},
        confidence={"top1_score": 0.9},
        latency={"total": 100},
        multi_commodity=[_cand("720839", 0.9), _cand("320820", 0.85)],
    )
    multi = payload["hs_classification"]["multi_commodity"]
    assert isinstance(multi, list)
    assert len(multi) == 2
    assert multi[0]["hs_code"] == "720839"
    assert multi[1]["hs_code"] == "320820"


def test_build_defaults_when_no_abstention_passed() -> None:
    payload = build(
        shipment_id=uuid4(),
        candidates=[_cand("720839", 0.9)],
        entities={},
        confidence={"top1_score": 0.9},
        latency={"total": 100},
    )
    hs = payload["hs_classification"]
    assert hs["abstained"] is False
    assert hs["abstain_reason"] is None
    assert hs["multi_commodity"] is None
