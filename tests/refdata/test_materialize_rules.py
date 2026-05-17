"""Pure-function tests for `materialize_rules.build_rule_fields` and `_build_phrases`.

DB-bound behavior (UPSERT, orphan deactivation) is covered in
`test_materialize_rules_db.py`; this file is pure and runs without Postgres.
"""
from __future__ import annotations

import pytest

from app.refdata.sanctions.materialize_rules import (
    DEFAULT_THRESHOLD,
    MAX_PHRASES,
    VALID_STRATEGIES,
    _build_phrases,
    _scope_token,
    _stable_record_token,
    build_rule_fields,
)


class TestBuildPhrases:
    def test_description_only_keeps_single_phrase(self) -> None:
        out = _build_phrases("Cuban rum, tobacco, cigars", aliases=["Habana"], strategy="description_only")
        assert out == ["Cuban rum, tobacco, cigars"]

    def test_with_aliases_appends_aliases(self) -> None:
        out = _build_phrases(
            "Iranian crude oil",
            aliases=["Iranian heavy crude", "naphtha"],
            strategy="with_aliases",
        )
        assert out == ["Iranian crude oil", "Iranian heavy crude", "naphtha"]

    def test_split_lists_splits_commas_semicolons_and(self) -> None:
        out = _build_phrases(
            "rum, tobacco; cigars and aged spirits",
            aliases=[],
            strategy="split_lists",
        )
        assert out[0] == "rum, tobacco; cigars and aged spirits"
        # Splits produce these tokens in some order — assert membership not order.
        rest = set(out[1:])
        assert {"rum", "tobacco", "cigars", "aged spirits"}.issubset(rest)

    def test_dedupes_case_insensitively(self) -> None:
        out = _build_phrases(
            "Crude oil, crude oil",
            aliases=["CRUDE OIL"],
            strategy="split_lists",
        )
        # Description plus one split token; alias is a dupe of description.
        assert len(out) == 2
        assert out[0] == "Crude oil, crude oil"

    def test_caps_at_max_phrases(self) -> None:
        # 14 distinct >=3-char tokens; result should be capped at MAX_PHRASES
        # (the description occupies slot 0, leaving MAX_PHRASES-1 splits).
        out = _build_phrases(
            "alpha, bravo, charlie, delta, echo, foxtrot, golf, hotel, india, juliet, kilo, lima, mike, november",
            aliases=[],
            strategy="split_lists",
        )
        assert len(out) == MAX_PHRASES

    def test_drops_short_fragments(self) -> None:
        # "a" and "b" are < 3 chars and should be filtered out.
        out = _build_phrases("a, b, crude oil", aliases=[], strategy="split_lists")
        assert "a" not in out
        assert "b" not in out
        assert "crude oil" in out

    def test_empty_description_returns_empty(self) -> None:
        assert _build_phrases("", aliases=["alias"], strategy="split_lists") == []
        assert _build_phrases("   ", aliases=[], strategy="split_lists") == []


class TestScopeAndToken:
    def test_scope_token_with_origin_and_dest(self) -> None:
        assert _scope_token("IR", "US") == "IR->US"

    def test_scope_token_null_origin(self) -> None:
        assert _scope_token(None, "KP") == "*->KP"

    def test_scope_token_both_null(self) -> None:
        assert _scope_token(None, None) == "*->*"

    def test_stable_record_token_prefers_source_record_id(self) -> None:
        commodity = {"source": "IRAN", "source_record_id": "IRAN-3", "description": "oil"}
        assert _stable_record_token(commodity) == "IRAN-3"

    def test_stable_record_token_falls_back_to_hash(self) -> None:
        a = _stable_record_token({"source": "X", "source_record_id": None, "description": "oil"})
        b = _stable_record_token({"source": "X", "source_record_id": None, "description": "oil"})
        c = _stable_record_token({"source": "X", "source_record_id": None, "description": "gold"})
        # Deterministic for same description, different for different.
        assert a == b
        assert a != c
        assert a.startswith("h")


class TestBuildRuleFields:
    def _commodity(self, **overrides):
        base = {
            "id": 1,
            "source": "IRAN",
            "source_record_id": "IRAN-0",
            "description": "Iranian-origin crude oil",
        }
        base.update(overrides)
        return base

    def _cr(self, origin=None, destination=None, conditions=None):
        return {
            "origin_iso": origin,
            "destination_iso": destination,
            "restriction_type": "blocked",
            "conditions": conditions,
        }

    def _cfg(self, **overrides):
        base = {
            "enabled": True,
            "default_threshold": 0.55,
            "phrase_strategy": "split_lists",
        }
        base.update(overrides)
        return base

    def test_returns_none_on_empty_description(self) -> None:
        result = build_rule_fields(
            self._commodity(description=""), aliases=[], country_rule=self._cr(), cfg=self._cfg()
        )
        assert result is None

    def test_basic_single_phrase_rule(self) -> None:
        # No splits, no aliases → no phrase_group, just legacy `phrase`.
        result = build_rule_fields(
            self._commodity(description="petroleum"),
            aliases=[],
            country_rule=self._cr(origin="IR"),
            cfg=self._cfg(),
        )
        assert result is not None
        assert result["phrase"] == "petroleum"
        assert result["phrase_group"] is None
        assert result["origin_iso"] == "IR"
        assert result["destination_iso"] is None
        assert result["threshold"] == 0.55
        assert result["created_by"] == "sanctions_source:IRAN"
        assert result["active"] is True

    def test_multi_phrase_creates_group(self) -> None:
        result = build_rule_fields(
            self._commodity(description="rum, tobacco, cigars"),
            aliases=["Habana Club"],
            country_rule=self._cr(origin="CU"),
            cfg=self._cfg(),
        )
        assert result is not None
        assert result["phrase"] == "rum, tobacco, cigars"
        pg = result["phrase_group"]
        assert pg is not None
        assert pg["mode"] == "any_of"
        # The split phrases + alias all show up.
        joined = " | ".join(pg["phrases"])
        assert "rum" in joined and "tobacco" in joined and "cigars" in joined
        assert "Habana Club" in joined

    def test_conditions_pass_through(self) -> None:
        conds = {"min_value": 1000, "currency_in": ["USD"]}
        result = build_rule_fields(
            self._commodity(description="luxury watches"),
            aliases=[],
            country_rule=self._cr(destination="KP", conditions=conds),
            cfg=self._cfg(),
        )
        assert result is not None
        assert result["conditions"] == conds

    def test_name_is_deterministic_across_calls(self) -> None:
        # Re-running the deriver with identical inputs must produce identical
        # `name` so the partial unique index UPSERTs in place.
        a = build_rule_fields(
            self._commodity(), aliases=[], country_rule=self._cr(origin="IR"), cfg=self._cfg()
        )
        b = build_rule_fields(
            self._commodity(), aliases=[], country_rule=self._cr(origin="IR"), cfg=self._cfg()
        )
        assert a is not None and b is not None
        assert a["name"] == b["name"]

    def test_name_distinguishes_scopes_for_direction_both(self) -> None:
        # `direction: both` in country_program ingest produces TWO country_rule
        # rows: (origin=country, dest=None) and (origin=None, dest=country).
        # Each must materialize to a distinct ScreeningRule with a distinct name.
        commodity = self._commodity(source="SYRIA", source_record_id="SYRIA-2")
        a = build_rule_fields(
            commodity, aliases=[], country_rule=self._cr(origin="SY"), cfg=self._cfg()
        )
        b = build_rule_fields(
            commodity, aliases=[], country_rule=self._cr(destination="SY"), cfg=self._cfg()
        )
        assert a is not None and b is not None
        assert a["name"] != b["name"]
        assert a["origin_iso"] == "SY" and a["destination_iso"] is None
        assert b["origin_iso"] is None and b["destination_iso"] == "SY"

    def test_invalid_strategy_falls_back_to_split_lists(self) -> None:
        result = build_rule_fields(
            self._commodity(description="rum, tobacco"),
            aliases=[],
            country_rule=self._cr(),
            cfg=self._cfg(phrase_strategy="bogus_value"),
        )
        assert result is not None
        # Got a phrase_group because split_lists split the description.
        assert result["phrase_group"] is not None

    @pytest.mark.parametrize("strategy", VALID_STRATEGIES)
    def test_every_documented_strategy_runs(self, strategy: str) -> None:
        out = build_rule_fields(
            self._commodity(description="luxury watches; gold jewelry"),
            aliases=["Rolex"],
            country_rule=self._cr(destination="KP"),
            cfg=self._cfg(phrase_strategy=strategy),
        )
        assert out is not None

    def test_threshold_default_used_when_cfg_missing_threshold(self) -> None:
        cfg = {"enabled": True, "phrase_strategy": "split_lists"}
        result = build_rule_fields(
            self._commodity(description="oil"), aliases=[], country_rule=self._cr(), cfg=cfg
        )
        assert result is not None
        assert result["threshold"] == DEFAULT_THRESHOLD
