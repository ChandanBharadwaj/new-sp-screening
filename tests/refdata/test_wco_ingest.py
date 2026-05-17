"""WCO HS XLSX parser tests (no DB)."""
import pandas as pd

from app.refdata.wco.ingest import _normalize_code, _roll_up


class TestNormalizeCode:
    def test_strips_dots(self) -> None:
        assert _normalize_code("01.01.21") == "010121"

    def test_strips_spaces(self) -> None:
        assert _normalize_code("7208 39") == "720839"

    def test_handles_none(self) -> None:
        assert _normalize_code(None) == ""
        assert _normalize_code(float("nan")) == ""

    def test_passes_through_digits(self) -> None:
        assert _normalize_code("720839") == "720839"


class TestRollUp:
    def test_single_subheading_emits_three_levels(self) -> None:
        df = pd.DataFrame(
            [{"HSCode": "010121", "Description": "Pure-bred breeding horses"}]
        )
        out = _roll_up(df)
        assert set(out.keys()) == {"01", "0101", "010121"}
        assert out["010121"]["level"] == 6
        assert out["010121"]["parent_code"] == "0101"
        assert out["0101"]["level"] == 4
        assert out["0101"]["parent_code"] == "01"
        assert out["01"]["level"] == 2
        assert out["01"]["parent_code"] is None
        assert out["010121"]["chapter"] == "01"

    def test_french_column_concatenated(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "HSCode": "010121",
                    "Description (EN)": "Pure-bred breeding horses",
                    "Description (FR)": "Chevaux reproducteurs de race pure",
                }
            ]
        )
        out = _roll_up(df)
        assert "Pure-bred breeding horses" in out["010121"]["description"]
        assert "Chevaux" in out["010121"]["description"]
        assert "||" in out["010121"]["description"]
        # Title is English only.
        assert out["010121"]["title"] == "Pure-bred breeding horses"

    def test_skips_rows_without_code_or_description(self) -> None:
        df = pd.DataFrame(
            [
                {"HSCode": "", "Description": "no code"},
                {"HSCode": "010121", "Description": ""},
                {"HSCode": "010129", "Description": "Other live horses"},
            ]
        )
        out = _roll_up(df)
        # Only the third row should produce rows.
        assert "010129" in out
        assert "010121" not in out

    def test_heading_keeps_longest_description(self) -> None:
        # Two subheadings under the same heading; the heading row's description
        # should be the longer of the two so the embedder sees the most context.
        df = pd.DataFrame(
            [
                {"HSCode": "010121", "Description": "Pure-bred horses"},
                {
                    "HSCode": "010129",
                    "Description": "Other live horses (asses, mules, hinnies)",
                },
            ]
        )
        out = _roll_up(df)
        assert "asses" in out["0101"]["description"]

    def test_chapter_4_only_code(self) -> None:
        # Some WCO sheets list heading-level rows without subheadings.
        df = pd.DataFrame([{"HSCode": "7208", "Description": "Flat-rolled iron"}])
        out = _roll_up(df)
        assert set(out.keys()) == {"72", "7208"}
        assert out["7208"]["level"] == 4
        assert out["72"]["level"] == 2
