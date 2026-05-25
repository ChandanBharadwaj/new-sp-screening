"""Unit tests for assemble.group_rule_matches_by_list."""
from __future__ import annotations

from app.pipeline.assemble import group_rule_matches_by_list


def _match(*, created_by: str | None, phrase: str, sim: float, threshold: float = 0.5) -> dict:
    return {
        "rule_id": 1,
        "rule_name": f"{created_by}::row",
        "phrase": phrase,
        "phrase_similarity": sim,
        "threshold": threshold,
        "delta_above_threshold": round(sim - threshold, 4),
        "conditions_satisfied": True,
        "created_by": created_by,
    }


def test_empty_returns_empty() -> None:
    assert group_rule_matches_by_list([]) == []


def test_groups_only_keyword_list_rows() -> None:
    matches = [
        _match(created_by="sanctions_source:OFAC_SDN", phrase="x", sim=0.9),
        _match(created_by=None, phrase="operator phrase", sim=0.7),
        _match(created_by="sanctions_source:KW:seafood", phrase="tuna", sim=0.8),
        _match(created_by="sanctions_source:KW:seafood", phrase="cod", sim=0.6),
        _match(created_by="sanctions_source:KW:chemicals", phrase="acid", sim=0.4),
    ]
    out = group_rule_matches_by_list(matches)
    assert {g["list"] for g in out} == {"seafood", "chemicals"}
    # Sorted by top_similarity desc.
    assert out[0]["list"] == "seafood"
    assert out[0]["top_phrase"] == "tuna"
    assert out[0]["top_similarity"] == 0.8
    assert out[0]["n_total"] == 2
    assert out[0]["n_above_threshold"] == 2  # both tuna(0.8) and cod(0.6) ≥ 0.5

    chem = next(g for g in out if g["list"] == "chemicals")
    assert chem["n_above_threshold"] == 0  # 0.4 < 0.5


def test_conditions_unsatisfied_excluded_from_above_threshold() -> None:
    m = _match(created_by="sanctions_source:KW:seafood", phrase="tuna", sim=0.9)
    m["conditions_satisfied"] = False
    out = group_rule_matches_by_list([m])
    assert out[0]["n_above_threshold"] == 0
    assert out[0]["n_total"] == 1
