"""Unit tests for /api/v1/results filter SQL composition (no DB)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.routes_results import _apply_filters
from app.db.models import ScreeningResult, Shipment


def _compiled(**filters: object) -> str:
    base = select(ScreeningResult, Shipment).join(
        Shipment, Shipment.id == ScreeningResult.shipment_id
    )
    stmt = _apply_filters(base, **filters)
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


_DEFAULTS = dict(
    origin_iso=None,
    destination_iso=None,
    abstained=None,
    has_sanctions=None,
    has_rules=None,
    since=None,
    chapter=None,
    min_score=None,
)


class TestFilters:
    def test_no_filters_no_where(self) -> None:
        sql = _compiled(**_DEFAULTS)
        # The implicit JOIN ON clause is always present; check no other WHERE was added.
        assert " where " not in sql.split(" on ", 1)[1]

    def test_origin_destination_filters(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"origin_iso": "DE", "destination_iso": "IR"}))
        assert "shipment.origin_iso = 'de'".lower() in sql.lower()
        assert "shipment.destination_iso = 'ir'".lower() in sql.lower()

    def test_since_filter(self) -> None:
        sql = _compiled(
            **(_DEFAULTS | {"since": datetime(2026, 1, 1, tzinfo=timezone.utc)})
        )
        assert "screening_result.created_at >=" in sql

    def test_abstained_true(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"abstained": True}))
        assert "hs_candidates ->> 'abstained'" in sql
        assert "'true'" in sql

    def test_abstained_false_uses_or_with_null(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"abstained": False}))
        assert "is null" in sql
        # Should not require abstained='true'
        assert "abstained" in sql

    def test_has_sanctions_true(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"has_sanctions": True}))
        assert "jsonb_array_length" in sql
        assert "sanction_matches" in sql and "'items'" in sql

    def test_has_sanctions_false(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"has_sanctions": False}))
        assert "jsonb_array_length" in sql
        assert "= 0" in sql or "= 0)" in sql

    def test_has_rules_true(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"has_rules": True}))
        assert "rule_matches" in sql and "'items'" in sql

    def test_chapter_filter(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"chapter": "72"}))
        # Top1 chapter is in hs_candidates.top_candidates[0].chapter
        assert "top_candidates" in sql
        assert "'72'" in sql

    def test_min_score_filter(self) -> None:
        sql = _compiled(**(_DEFAULTS | {"min_score": 0.5}))
        assert "top_candidates" in sql
        assert "score" in sql
        assert ">=" in sql

    def test_combined_filters_all_present(self) -> None:
        sql = _compiled(
            **(
                _DEFAULTS
                | {
                    "origin_iso": "US",
                    "abstained": True,
                    "has_sanctions": True,
                    "since": datetime(2026, 5, 1, tzinfo=timezone.utc),
                }
            )
        )
        assert "origin_iso = 'us'" in sql.lower()
        assert "hs_candidates ->> 'abstained'" in sql
        assert "sanction_matches" in sql and "'items'" in sql
        assert "created_at >=" in sql


@pytest.mark.parametrize("abstained_value", [True, False])
def test_abstained_none_omits_predicate(abstained_value: bool) -> None:
    """When abstained=None, no predicate on hs_candidates['abstained'] is emitted.

    Sanity check: passing abstained=<value> *does* emit the predicate, so the
    None branch isn't a no-op accident.
    """
    sql_with = _compiled(**(_DEFAULTS | {"abstained": abstained_value}))
    sql_without = _compiled(**_DEFAULTS)
    assert "abstained" in sql_with
    assert "abstained" not in sql_without
