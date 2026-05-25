"""Unit tests for the keyword-list CSV parser. No DB required."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.refdata.keyword_lists import ingest


def _write_csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "keywords.csv"
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_csv_basic(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "keywords\nyellowfin tuna\nbluefin tuna\ncaviar\n")
    assert ingest.parse_csv(p) == ["yellowfin tuna", "bluefin tuna", "caviar"]


def test_parse_csv_strips_whitespace_and_dedupes_case_insensitive(tmp_path: Path) -> None:
    p = _write_csv(
        tmp_path,
        "keywords\n  yellowfin tuna  \nYELLOWFIN TUNA\nyellowfin tuna\nbluefin\n",
    )
    assert ingest.parse_csv(p) == ["yellowfin tuna", "bluefin"]


def test_parse_csv_drops_short_entries(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "keywords\nab\ncod\n  \nshrimp\n")
    # "ab" is < MIN_KEYWORD_LEN=3, blank is also dropped.
    assert ingest.parse_csv(p) == ["cod", "shrimp"]


def test_parse_csv_accepts_alternate_header_names(tmp_path: Path) -> None:
    for header in ("keyword", "Keywords", "phrase", "Phrases"):
        p = _write_csv(tmp_path, f"{header}\nyellowfin tuna\nbluefin tuna\n")
        assert ingest.parse_csv(p) == ["yellowfin tuna", "bluefin tuna"]


def test_parse_csv_missing_required_column_raises(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "term,note\nfoo,bar\n")
    with pytest.raises(ValueError, match="must have a 'keywords' column"):
        ingest.parse_csv(p)


def test_parse_csv_empty_file_returns_empty_list(tmp_path: Path) -> None:
    p = _write_csv(tmp_path, "")
    assert ingest.parse_csv(p) == []


def test_parse_csv_strips_utf8_bom(tmp_path: Path) -> None:
    # Excel-exported CSVs carry a BOM; the header must still match.
    p = tmp_path / "keywords.csv"
    p.write_bytes(b"\xef\xbb\xbfkeywords\nyellowfin tuna\ncaviar\n")
    assert ingest.parse_csv(p) == ["yellowfin tuna", "caviar"]


def test_source_key_uses_short_prefix() -> None:
    assert ingest.source_key("seafood") == "KW:seafood"
    # Stay under the SanctionedCommodity.source String(32) cap.
    assert len(ingest.source_key("a" * 29)) == 32


def test_build_rows_global_scope_no_country_rule_pair() -> None:
    from app.db.models import KeywordList

    m = KeywordList(
        name="seafood",
        origin_iso=None,
        destination_iso=None,
        direction=None,
        restriction_type="watchlist",
        default_threshold=0.55,
    )
    rows = ingest.build_rows("seafood", ["caviar", "shrimp"], m)
    assert len(rows) == 2
    # Content-addressed id (not positional) so edits don't collide under
    # ON CONFLICT DO NOTHING. Stable + deterministic for a given phrase.
    assert rows[0]["source_record_id"] == ingest._record_id("KW:seafood", "caviar")
    assert rows[0]["source_record_id"].startswith("KW:seafood-")
    assert rows[0]["source_record_id"] != rows[1]["source_record_id"]
    assert rows[0]["description"] == "caviar"
    assert rows[0]["hs_codes"] == []  # semantic-only by default
    assert rows[0]["country_rules"] == [
        {
            "origin_iso": None,
            "destination_iso": None,
            "restriction_type": "watchlist",
        }
    ]


def test_record_id_is_stable_and_content_addressed() -> None:
    # Same phrase → same id (idempotent re-runs); different phrase → different id
    # (edited keyword orphan-deletes the old row instead of silently keeping it).
    assert ingest._record_id("KW:s", "tuna") == ingest._record_id("KW:s", "tuna")
    assert ingest._record_id("KW:s", "tuna") != ingest._record_id("KW:s", "salmon")


def test_build_rows_export_to_scope() -> None:
    from app.db.models import KeywordList

    m = KeywordList(
        name="seafood",
        origin_iso=None,
        destination_iso="IR",
        direction="export_to",
        restriction_type="blocked",
        default_threshold=0.55,
    )
    rows = ingest.build_rows("seafood", ["caviar"], m)
    assert rows[0]["country_rules"] == [
        {"origin_iso": None, "destination_iso": "IR", "restriction_type": "blocked"}
    ]


def test_build_rows_import_from_scope() -> None:
    from app.db.models import KeywordList

    m = KeywordList(
        name="seafood",
        origin_iso="IR",
        destination_iso=None,
        direction="import_from",
        restriction_type="blocked",
        default_threshold=0.55,
    )
    rows = ingest.build_rows("seafood", ["caviar"], m)
    assert rows[0]["country_rules"] == [
        {"origin_iso": "IR", "destination_iso": None, "restriction_type": "blocked"}
    ]


def test_build_rows_both_directions() -> None:
    from app.db.models import KeywordList

    m = KeywordList(
        name="seafood",
        origin_iso="IR",
        destination_iso="US",
        direction="both",
        restriction_type="blocked",
        default_threshold=0.55,
    )
    rows = ingest.build_rows("seafood", ["caviar"], m)
    assert rows[0]["country_rules"] == [
        {"origin_iso": "IR", "destination_iso": None, "restriction_type": "blocked"},
        {"origin_iso": None, "destination_iso": "US", "restriction_type": "blocked"},
    ]
