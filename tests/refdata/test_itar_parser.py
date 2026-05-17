"""ITAR USML CSV parser tests (no DB)."""
import csv
from pathlib import Path

from app.refdata.sanctions.itar.ingest import _parse


def _write_csv(p: Path, rows: list[dict]) -> None:
    with p.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestItarParser:
    def test_minimal_row(self, tmp_path: Path) -> None:
        p = tmp_path / "usml.csv"
        _write_csv(
            p,
            [
                {
                    "usml_category": "I",
                    "paragraph": "(a)(1)",
                    "description": "Firearms 0.50 caliber and below",
                    "hs_codes": "930320",
                }
            ],
        )
        items = _parse(p)
        assert len(items) == 1
        r = items[0]
        assert r["source_record_id"].startswith("USML-I(a)(1)-")
        assert "Firearms" in r["description"]
        assert r["hs_codes"] == ["930320"]
        assert r["restriction_type"] == "export_controlled"
        # ITAR always attaches a US-origin export control with no destination filter.
        assert r["country_rules"] == [
            {"origin_iso": "US", "destination_iso": None, "restriction_type": "export_controlled"}
        ]

    def test_skips_missing_required(self, tmp_path: Path) -> None:
        p = tmp_path / "usml.csv"
        _write_csv(
            p,
            [
                {"usml_category": "II", "paragraph": "", "description": "", "hs_codes": ""},
                {"usml_category": "", "paragraph": "", "description": "no category", "hs_codes": ""},
                {
                    "usml_category": "III",
                    "paragraph": "(a)",
                    "description": "Ammunition for Cat II articles",
                    "hs_codes": "",
                },
            ],
        )
        items = _parse(p)
        assert len(items) == 1
        assert "Ammunition" in items[0]["description"]
        assert items[0]["hs_codes"] == []

    def test_multiple_hs_codes(self, tmp_path: Path) -> None:
        p = tmp_path / "usml.csv"
        _write_csv(
            p,
            [
                {
                    "usml_category": "VIII",
                    "paragraph": "(a)",
                    "description": "Aircraft & related articles",
                    "hs_codes": "880240; 880330; 880390",
                }
            ],
        )
        items = _parse(p)
        assert items[0]["hs_codes"] == ["880240", "880330", "880390"]

    def test_restriction_override(self, tmp_path: Path) -> None:
        p = tmp_path / "usml.csv"
        _write_csv(
            p,
            [
                {
                    "usml_category": "I",
                    "paragraph": "",
                    "description": "Restricted article",
                    "hs_codes": "",
                    "restriction_type": "blocked",
                }
            ],
        )
        items = _parse(p)
        assert items[0]["restriction_type"] == "blocked"
        assert items[0]["country_rules"][0]["restriction_type"] == "blocked"
