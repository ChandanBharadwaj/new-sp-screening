"""NER span dedup and shape (no GLiNER load)."""
from app.models.ner_model import _dedup_spans


def test_preserves_offsets_and_score() -> None:
    out = _dedup_spans(
        [
            {"label": "material", "text": "stainless steel", "start": 0, "end": 15, "score": 0.92},
            {"label": "form", "text": "coil", "start": 16, "end": 20, "score": 0.85},
        ]
    )
    assert out["material"][0]["start"] == 0
    assert out["material"][0]["end"] == 15
    assert out["material"][0]["text"] == "stainless steel"
    assert out["material"][0]["score"] == 0.92
    assert out["form"][0]["text"] == "coil"


def test_dedup_keeps_highest_score_per_label() -> None:
    out = _dedup_spans(
        [
            {"label": "material", "text": "Steel", "start": 0, "end": 5, "score": 0.6},
            {"label": "material", "text": "steel", "start": 20, "end": 25, "score": 0.9},
            {"label": "material", "text": "STEEL", "start": 40, "end": 45, "score": 0.7},
        ]
    )
    assert len(out["material"]) == 1
    span = out["material"][0]
    assert span["score"] == 0.9
    # Highest-score occurrence's original text + offsets are preserved.
    assert span["start"] == 20
    assert span["text"] == "steel"


def test_same_text_different_labels_kept_separately() -> None:
    out = _dedup_spans(
        [
            {"label": "material", "text": "iron", "start": 0, "end": 4, "score": 0.8},
            {"label": "end_use", "text": "iron", "start": 0, "end": 4, "score": 0.7},
        ]
    )
    assert "material" in out and "end_use" in out
    assert out["material"][0]["text"] == "iron"
    assert out["end_use"][0]["text"] == "iron"


def test_empty_input_returns_empty_dict() -> None:
    assert _dedup_spans([]) == {}


def test_missing_score_treated_as_zero() -> None:
    out = _dedup_spans(
        [
            {"label": "material", "text": "wood", "start": 0, "end": 4},
            {"label": "material", "text": "wood", "start": 10, "end": 14, "score": 0.5},
        ]
    )
    # Second wins because 0.5 > implicit 0.0.
    assert out["material"][0]["start"] == 10
