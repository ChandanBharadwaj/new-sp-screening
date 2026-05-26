from __future__ import annotations

from eval.calibration.synthetic import build_synthetic

GOLD = [
    {"description": "seamless steel pipe for oil drilling", "hs_code": "730419"},
    {"description": "stainless steel tube fittings", "hs_code": "730722"},
    {"description": "fresh atlantic salmon fillet", "hs_code": "030441"},
    {"description": "frozen yellowfin tuna loin", "hs_code": "030487"},
]


def test_includes_real_examples_unmodified() -> None:
    out = build_synthetic(GOLD, per_record=0)
    reals = [r for r in out if r["kind"] == "real"]
    assert len(reals) == len(GOLD)
    assert {r["description"] for r in reals} == {g["description"] for g in GOLD}


def test_perturbations_carry_correct_label() -> None:
    out = build_synthetic(GOLD, per_record=3, seed=1)
    by_desc = {g["description"]: g["hs_code"] for g in GOLD}
    for r in out:
        if r["kind"] == "drop_noun":
            # token dropped → still labelled with the original code's chapter family
            assert len(r["hs_code"]) == 6
        if r["kind"] in ("in_chapter_swap", "cross_chapter_swap"):
            # swapped descriptions keep the borrowed item's own (correct) code
            assert r["description"] in by_desc
            assert r["hs_code"] == by_desc[r["description"]]


def test_deterministic_with_seed() -> None:
    a = build_synthetic(GOLD, per_record=2, seed=7)
    b = build_synthetic(GOLD, per_record=2, seed=7)
    assert a == b
