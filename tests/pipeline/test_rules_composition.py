"""Rule composition tests.

Pure unit tests against the score-combining helpers, no DB and no reranker.
The score() entrypoint itself is integration-tested via the API job — not
covered here.
"""
from app.pipeline.rules import _combine, _phrases_for


class _StubRule:
    """Minimal duck-type stand-in for ScreeningRule used by _phrases_for."""

    def __init__(self, phrase: str = "default", phrase_group: dict | None = None) -> None:
        self.phrase = phrase
        self.phrase_group = phrase_group


class TestPhrasesFor:
    def test_single_phrase_legacy(self) -> None:
        rule = _StubRule(phrase="dual-use chemicals")
        phrases, mode = _phrases_for(rule)
        assert phrases == ["dual-use chemicals"]
        assert mode == "single"

    def test_any_of(self) -> None:
        rule = _StubRule(
            phrase="dual-use",
            phrase_group={"mode": "any_of", "phrases": ["chemicals", "weapons"]},
        )
        phrases, mode = _phrases_for(rule)
        assert phrases == ["chemicals", "weapons"]
        assert mode == "any_of"

    def test_all_of(self) -> None:
        rule = _StubRule(
            phrase="dual-use",
            phrase_group={"mode": "all_of", "phrases": ["chemicals", "embargoed"]},
        )
        phrases, mode = _phrases_for(rule)
        assert phrases == ["chemicals", "embargoed"]
        assert mode == "all_of"

    def test_empty_group_falls_back_to_phrase(self) -> None:
        rule = _StubRule(phrase="fallback", phrase_group={"mode": "any_of", "phrases": []})
        phrases, mode = _phrases_for(rule)
        assert phrases == ["fallback"]
        assert mode == "single"

    def test_unknown_mode_defaults_to_any_of(self) -> None:
        rule = _StubRule(
            phrase="x",
            phrase_group={"mode": "weird", "phrases": ["a", "b"]},
        )
        _, mode = _phrases_for(rule)
        assert mode == "any_of"


class TestCombine:
    def test_any_of_uses_max(self) -> None:
        assert _combine([0.2, 0.9], "any_of") == 0.9

    def test_all_of_uses_min(self) -> None:
        assert _combine([0.2, 0.9], "all_of") == 0.2

    def test_single_uses_max_of_one(self) -> None:
        assert _combine([0.5], "single") == 0.5

    def test_empty_returns_zero(self) -> None:
        assert _combine([], "any_of") == 0.0
        assert _combine([], "all_of") == 0.0
