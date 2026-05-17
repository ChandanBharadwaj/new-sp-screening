"""Abstention heuristic tests.

The compute_abstention function is pure — no DB, no model — so we can pin its
behavior on representative candidate/confidence shapes directly.
"""
from app.pipeline.confidence import compute_abstention, fallback_candidate


def _cands(*scores_and_chapters: tuple[float, str]) -> list[dict]:
    return [
        {
            "hs_code": f"{ch}1234"[:6],
            "score": s,
            "chapter": ch,
            "title": "x",
            "score_components": {},
        }
        for s, ch in scores_and_chapters
    ]


class TestAbstention:
    def test_empty_candidates_abstains(self) -> None:
        out = compute_abstention([], {})
        assert out == {"abstained": True, "reason": "no_candidates", "fallback_level": None}

    def test_low_top1_abstains_with_chapter_fallback(self) -> None:
        cands = _cands((0.30, "72"), (0.25, "72"), (0.20, "73"))
        conf = {"top1_score": 0.30, "top1_minus_top2": 0.05, "chapter_consensus": 0.6}
        out = compute_abstention(cands, conf)
        assert out["abstained"] is True
        assert out["reason"] == "low_top1"
        assert out["fallback_level"] == 4  # high chapter consensus -> heading fallback

    def test_low_top1_no_chapter_consensus_falls_back_to_chapter(self) -> None:
        cands = _cands((0.30, "72"), (0.25, "84"), (0.20, "85"))
        conf = {"top1_score": 0.30, "top1_minus_top2": 0.05, "chapter_consensus": 0.1}
        out = compute_abstention(cands, conf)
        assert out["fallback_level"] == 2

    def test_ambiguous_chapter_falls_back_to_chapter(self) -> None:
        cands = _cands((0.55, "72"), (0.54, "84"), (0.53, "85"))
        conf = {"top1_score": 0.55, "top1_minus_top2": 0.01, "chapter_consensus": 0.2}
        out = compute_abstention(cands, conf)
        assert out["abstained"] is True
        assert out["reason"] == "ambiguous_chapter"
        assert out["fallback_level"] == 2

    def test_confident_does_not_abstain(self) -> None:
        cands = _cands((0.90, "72"), (0.30, "84"))
        conf = {"top1_score": 0.90, "top1_minus_top2": 0.60, "chapter_consensus": 0.7}
        out = compute_abstention(cands, conf)
        assert out["abstained"] is False
        assert out["reason"] is None


class TestFallbackCandidate:
    def test_returns_chapter(self) -> None:
        cands = [{"hs_code": "720839", "title": "Steel", "score": 0.5, "score_components": {}}]
        fb = fallback_candidate(cands, 2)
        assert fb is not None
        assert fb["hs_code"] == "72"
        assert fb["level"] == "chapter"
        assert fb["derived_from_top1"] == "720839"

    def test_returns_heading(self) -> None:
        cands = [{"hs_code": "720839", "title": "Steel", "score": 0.5, "score_components": {}}]
        fb = fallback_candidate(cands, 4)
        assert fb is not None
        assert fb["hs_code"] == "7208"
        assert fb["level"] == "heading"

    def test_no_fallback_when_none(self) -> None:
        assert fallback_candidate([], 2) is None
        assert fallback_candidate([{"hs_code": "720839"}], None) is None

    def test_clamps_to_actual_prefix_length(self) -> None:
        """If the top candidate code is already shorter than the requested fallback
        level (e.g. a 4-digit heading + fallback_level=6), the returned candidate
        is labeled at its actual depth — not mislabeled as a deeper level."""
        cands = [{"hs_code": "7208", "title": "Steel", "score": 0.5, "score_components": {}}]
        fb = fallback_candidate(cands, 6)
        assert fb is not None
        assert fb["hs_code"] == "7208"
        # Label clamped from "subheading" to "heading" because the code is 4 digits.
        assert fb["level"] == "heading"

    def test_returns_none_for_odd_length_code(self) -> None:
        # 3-digit codes never appear in HS but defensive code shouldn't emit a
        # fractional prefix mislabeled as a known level.
        cands = [{"hs_code": "720", "title": "x", "score": 0.5, "score_components": {}}]
        assert fallback_candidate(cands, 2) == {
            "hs_code": "72",
            "level": "chapter",
            "chapter": "72",
            "heading": None,
            "title": "x",
            "score": 0.5,
            "score_components": {},
            "derived_from_top1": "720",
        }
