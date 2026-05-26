from __future__ import annotations

from eval.calibration.registry import REGISTRY, Threshold, by_kind


def test_kinds_are_valid_and_partitioned() -> None:
    kinds = {t.kind for t in REGISTRY}
    assert kinds <= {"post_hoc", "retrieval", "reported_only"}
    assert len(REGISTRY) == len(by_kind("post_hoc")) + len(by_kind("retrieval")) + len(by_kind("reported_only"))


def test_names_unique() -> None:
    names = [t.name for t in REGISTRY]
    assert len(names) == len(set(names))


def test_db_backed_have_store_reported_only_do_not() -> None:
    for t in REGISTRY:
        if t.kind == "reported_only":
            assert t.store is None
        else:
            assert t.store is not None and t.store[0] in ("inference_threshold", "policy_parameter")


def test_post_hoc_have_feature_keys() -> None:
    for t in by_kind("post_hoc"):
        assert t.feature, f"{t.name} missing feature key"


def test_sweep_values_inclusive_and_ordered() -> None:
    t = Threshold("x", "post_hoc", 0.4, 0.30, 0.60, 0.1, ("inference_threshold", "p", "q"), feature="f")
    vals = t.sweep_values()
    assert vals[0] == 0.30
    assert vals[-1] == 0.60
    assert vals == sorted(vals)


def test_known_thresholds_present() -> None:
    names = {t.name for t in REGISTRY}
    for expected in (
        "min_top1", "min_gap", "min_chapter_consensus",
        "cross_source_dense_floor", "cross_source_ce_floor",
        "gliner_min_score", "alias_min_similarity", "decompose_conf_gate",
    ):
        assert expected in names
