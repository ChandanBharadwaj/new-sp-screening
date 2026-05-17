"""Country-program YAML ingester tests (no DB)."""
from pathlib import Path

import pytest

from app.refdata.sanctions.country_program.ingest import (
    VALID_DIRECTIONS,
    _country_rules,
    parse,
)


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

    def test_padding_short_hs_code(self, tmp_path: Path) -> None:
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
        # "72" → padded right with zeros to "720000".
        assert rows[0]["hs_codes"] == ["720000"]

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
