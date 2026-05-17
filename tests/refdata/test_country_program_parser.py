"""Country-program YAML ingester tests (no DB).

The DB-backed `_expand_prefixes` helper is tested with mocked sessions so we
don't need a live Postgres for these tests.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.refdata.sanctions.common import expand_hs_prefixes as _expand_prefixes
from app.refdata.sanctions.country_program.ingest import (
    VALID_DIRECTIONS,
    _country_rules,
    parse,
)


def _mock_db_returning(codes: list[str]) -> AsyncMock:
    """Build an AsyncMock session whose `.execute(...).scalars().all()` returns codes."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = codes
    db.execute = AsyncMock(return_value=result)
    return db


class TestCountryRules:
    def test_import_from(self) -> None:
        rules = _country_rules("IR", "import_from", "blocked")
        assert rules == [
            {"origin_iso": "IR", "destination_iso": None, "restriction_type": "blocked"}
        ]

    def test_export_to(self) -> None:
        rules = _country_rules("KP", "export_to", "prohibited")
        assert rules == [
            {"origin_iso": None, "destination_iso": "KP", "restriction_type": "prohibited"}
        ]

    def test_both(self) -> None:
        rules = _country_rules("SY", "both", "blocked")
        assert len(rules) == 2
        directions = {(r["origin_iso"], r["destination_iso"]) for r in rules}
        assert directions == {("SY", None), (None, "SY")}

    def test_default_when_missing(self) -> None:
        # Empty string is normalized to export_to.
        rules = _country_rules("IR", "", "blocked")
        assert rules[0]["destination_iso"] == "IR"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            _country_rules("IR", "bogus", "blocked")

    def test_valid_directions(self) -> None:
        assert set(VALID_DIRECTIONS) == {"import_from", "export_to", "both"}


class TestParse:
    def test_iran_seed_file_parses(self) -> None:
        # The seeded YAML files in data/sanctions/country_program/ are committed
        # as part of the catalog; they must parse cleanly.
        repo_root = Path(__file__).resolve().parents[2]
        p = repo_root / "data" / "sanctions" / "country_program" / "iran.yaml"
        source_key, country_iso, rows = parse(p)
        assert source_key == "IRAN"
        assert country_iso == "IR"
        assert len(rows) >= 3
        assert all("description" in r for r in rows)
        assert all("country_rules" in r and r["country_rules"] for r in rows)

    def test_minimal_inline(self, tmp_path: Path) -> None:
        p = tmp_path / "tiny.yaml"
        p.write_text(
            """
source: TEST_COUNTRY
country_iso: ZZ
provenance_url: http://example.com
restrictions:
  - description: "Test prohibition"
    hs_codes: ["270900"]
    restriction_type: blocked
    direction: import_from
""",
            encoding="utf-8",
        )
        source_key, iso, rows = parse(p)
        assert source_key == "TEST_COUNTRY"
        assert iso == "ZZ"
        assert len(rows) == 1
        r = rows[0]
        assert r["hs_codes"] == ["270900"]
        assert r["country_rules"][0]["origin_iso"] == "ZZ"

    def test_prefix_kept_unpadded(self, tmp_path: Path) -> None:
        """Short HS prefixes are stored as-is; expansion to 6-digit codes happens
        in `_expand_prefixes` against the live `hs_code` table at ingest time, not
        in `parse()`. Padding with zeros at parse time would create invalid HS codes
        (chapter 72 has no heading 7200) that never match real shipments."""
        p = tmp_path / "tiny.yaml"
        p.write_text(
            """
source: T
country_iso: ZZ
restrictions:
  - description: "Steel chapter only"
    hs_codes: ["72"]
    direction: export_to
""",
            encoding="utf-8",
        )
        _, _, rows = parse(p)
        assert rows[0]["hs_codes"] == ["72"]

    def test_rejects_odd_length_codes(self, tmp_path: Path) -> None:
        """3-digit and 5-digit codes are typos; HS prefixes are valid only at
        chapter (2), heading (4), or subheading (6) depth."""
        p = tmp_path / "bad.yaml"
        p.write_text(
            """
source: T
country_iso: ZZ
restrictions:
  - description: "Bogus 5-digit"
    hs_codes: ["72083"]
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="2-, 4-, or 6-digit"):
            parse(p)

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("country_iso: ZZ\nrestrictions: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="source"):
            parse(p)

    def test_invalid_iso_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("source: T\ncountry_iso: USA\nrestrictions: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="country_iso"):
            parse(p)

    def test_skips_row_without_description(self, tmp_path: Path) -> None:
        p = tmp_path / "tiny.yaml"
        p.write_text(
            """
source: T
country_iso: ZZ
restrictions:
  - description: ""
    hs_codes: ["720000"]
  - description: "Valid one"
    hs_codes: ["720000"]
""",
            encoding="utf-8",
        )
        _, _, rows = parse(p)
        assert len(rows) == 1
        assert rows[0]["description"] == "Valid one"


class TestExpandPrefixes:
    async def test_six_digit_passthrough(self) -> None:
        db = _mock_db_returning([])  # query never used
        out = await _expand_prefixes(db, ["271019"])
        assert out == ["271019"]
        # No DB call should fire for an already-6-digit code.
        db.execute.assert_not_called()

    async def test_prefix_expansion(self) -> None:
        db = _mock_db_returning(["271011", "271012", "271019"])
        out = await _expand_prefixes(db, ["2710"])
        assert out == ["271011", "271012", "271019"]
        db.execute.assert_called_once()

    async def test_missing_prefix_dropped_with_warning(self) -> None:
        db = _mock_db_returning([])  # HS taxonomy returns nothing for this prefix
        out = await _expand_prefixes(db, ["99"])
        assert out == []  # silently drop rather than persist a non-matching code

    async def test_mixed_input_dedups_and_sorts(self) -> None:
        # Same code arriving via both a literal 6-digit and a 4-digit prefix expansion.
        result_codes = ["271011", "271019"]
        db = _mock_db_returning(result_codes)
        out = await _expand_prefixes(db, ["271011", "2710"])
        assert out == ["271011", "271019"]

    async def test_empty(self) -> None:
        db = _mock_db_returning([])
        assert await _expand_prefixes(db, []) == []
        db.execute.assert_not_called()


class TestSeededCountryFiles:
    @pytest.mark.parametrize(
        "slug,source,iso",
        [
            ("iran", "IRAN", "IR"),
            ("dprk", "DPRK", "KP"),
            ("syria", "SYRIA", "SY"),
            ("cuba", "CUBA", "CU"),
            ("venezuela", "VENEZUELA", "VE"),
        ],
    )
    def test_each_seed_parses_with_expected_metadata(
        self, slug: str, source: str, iso: str
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        p = repo_root / "data" / "sanctions" / "country_program" / f"{slug}.yaml"
        s, c, rows = parse(p)
        assert s == source
        assert c == iso
        assert len(rows) >= 1
