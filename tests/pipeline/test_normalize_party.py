from app.pipeline.normalize_party import (
    fold_unicode,
    is_short_name,
    normalize_party,
    strip_corp_suffix,
)


class TestFoldUnicode:
    def test_strips_diacritics(self) -> None:
        assert fold_unicode("Müller") == "Muller"
        assert fold_unicode("Société Générale") == "Societe Generale"
        assert fold_unicode("Citroën") == "Citroen"

    def test_passthrough_ascii(self) -> None:
        assert fold_unicode("ACME Ltd") == "ACME Ltd"

    def test_drops_non_latin(self) -> None:
        # Cyrillic and CJK currently pass through as empty (transliteration is out of scope).
        assert fold_unicode("Иванов") == ""
        assert fold_unicode("中国") == ""

    def test_empty(self) -> None:
        assert fold_unicode("") == ""


class TestStripCorpSuffix:
    def test_simple(self) -> None:
        assert strip_corp_suffix("ACME Ltd.") == "ACME"
        assert strip_corp_suffix("ACME Ltd") == "ACME"

    def test_multiple(self) -> None:
        # Repeatedly strip until stable.
        assert strip_corp_suffix("ACME Holdings Ltd") == "ACME"

    def test_with_dots(self) -> None:
        assert strip_corp_suffix("Foo S.A.R.L.") == "Foo"
        assert strip_corp_suffix("Bar S.p.A.") == "Bar"

    def test_no_match(self) -> None:
        assert strip_corp_suffix("PlainName") == "PlainName"


class TestNormalizeParty:
    def test_full_pipeline(self) -> None:
        assert normalize_party("ACME Holdings Ltd.") == "acme"
        assert normalize_party("Müller GmbH") == "muller"
        assert normalize_party("Société Générale S.A.") == "societe generale"

    def test_collapses_whitespace(self) -> None:
        assert normalize_party("  Foo   Bar  ") == "foo bar"


class TestIsShortName:
    def test_short(self) -> None:
        assert is_short_name("Smith") is True
        assert is_short_name("Lee") is True
        assert is_short_name("") is True

    def test_long(self) -> None:
        assert is_short_name("John Smith") is False
        assert is_short_name("Acme Holdings Corp") is False

    def test_single_long_token_still_short(self) -> None:
        # "Petrochemical" is one token; min_tokens=2 makes this still short.
        assert is_short_name("Petrochemical") is True
