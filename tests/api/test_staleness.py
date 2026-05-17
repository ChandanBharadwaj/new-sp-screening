"""Tests for the staleness helpers exposed via routes_status (pure functions)."""
from datetime import datetime, timedelta, timezone

from app.api.routes_status import _staleness_days, _staleness_severity


class TestStalenessDays:
    def test_none_returns_none(self) -> None:
        assert _staleness_days(None) is None

    def test_zero_for_recent(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        assert _staleness_days(recent) == 0

    def test_days_match(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=10, hours=1)
        assert _staleness_days(old) == 10

    def test_naive_datetime_treated_as_utc(self) -> None:
        # Some DBs return naive datetimes; the helper must not crash.
        naive = datetime.utcnow() - timedelta(days=3)
        result = _staleness_days(naive)
        assert result is not None and 2 <= result <= 3


class TestStalenessSeverity:
    def test_gray_when_unknown(self) -> None:
        assert _staleness_severity(None, sanctions=True) == "gray"
        assert _staleness_severity(None, sanctions=False) == "gray"

    def test_sanctions_thresholds(self) -> None:
        assert _staleness_severity(0, sanctions=True) == "green"
        assert _staleness_severity(7, sanctions=True) == "green"
        assert _staleness_severity(8, sanctions=True) == "amber"
        assert _staleness_severity(30, sanctions=True) == "amber"
        assert _staleness_severity(31, sanctions=True) == "red"

    def test_taxonomy_thresholds_are_lax(self) -> None:
        # HS taxonomy: green up to 90d, amber up to 365d, red after.
        assert _staleness_severity(60, sanctions=False) == "green"
        assert _staleness_severity(180, sanctions=False) == "amber"
        assert _staleness_severity(400, sanctions=False) == "red"
