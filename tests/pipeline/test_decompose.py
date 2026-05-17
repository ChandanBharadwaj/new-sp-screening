"""Multi-commodity decomposition tests."""
from app.pipeline.decompose import split_into_commodities


class TestDecompose:
    def test_empty_text(self) -> None:
        out = split_into_commodities("", {})
        assert out.confidence == 0.0
        assert len(out.fragments) == 1
        assert out.fragments[0].text == ""

    def test_single_commodity_passthrough(self) -> None:
        out = split_into_commodities("stainless steel coil 304 grade", {"material": ["steel"]})
        # Single commodity → confidence 0, one fragment.
        assert out.confidence == 0.0
        assert len(out.fragments) == 1

    def test_steel_and_paint_splits(self) -> None:
        text = "1000T steel coil + 500L industrial paint"
        ents = {"material": ["steel", "paint"]}
        out = split_into_commodities(text, ents)
        assert out.confidence >= 0.5
        assert len(out.fragments) == 2
        materials_by_frag = [f.materials for f in out.fragments]
        # Each fragment should carry exactly one distinct material.
        assert any("steel" in m for m in materials_by_frag)
        assert any("paint" in m for m in materials_by_frag)

    def test_split_on_semicolon(self) -> None:
        out = split_into_commodities(
            "copper wire; aluminum sheet", {"material": ["copper", "aluminum"]}
        )
        assert out.confidence >= 0.5
        assert len(out.fragments) == 2

    def test_split_on_and(self) -> None:
        out = split_into_commodities(
            "copper wire and aluminum sheet", {"material": ["copper", "aluminum"]}
        )
        assert out.confidence >= 0.5
        assert len(out.fragments) == 2

    def test_too_many_fragments_falls_back(self) -> None:
        # Six comma-separated fragments → > MAX_FRAGMENTS → single.
        text = "a + b + c + d + e + f + g"
        out = split_into_commodities(text, {"material": ["a", "b", "c", "d", "e", "f", "g"]})
        assert out.confidence == 0.0
        assert len(out.fragments) == 1

    def test_same_material_does_not_split(self) -> None:
        # Two fragments but same material → still single commodity.
        out = split_into_commodities("steel coil + steel plate", {"material": ["steel"]})
        assert out.confidence == 0.0
        assert len(out.fragments) == 1
