from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from app.config import settings

CUSTOMS_LABELS = [
    "material",
    "form",
    "end_use",
    "processing_state",
    "composition_percentages",
    "dimensions",
]


class NerModel:
    """Wraps GLiNER for customs entity extraction.

    `predict` returns structured spans (text + character offsets + score)
    so the UI can highlight matches over the original input. Duplicate
    surface forms within a single label are deduped by case-folded text,
    keeping the highest-score occurrence.
    """

    def __init__(self, labels: list[str] | None = None) -> None:
        from gliner import GLiNER

        t0 = time.perf_counter()
        self.model = GLiNER.from_pretrained(settings.ner_model)
        self.load_time_ms = int((time.perf_counter() - t0) * 1000)
        self.labels = labels or CUSTOMS_LABELS
        self.last_call_ms: int | None = None

    def predict(self, text: str) -> dict[str, list[dict[str, Any]]]:
        t0 = time.perf_counter()
        ents = self.model.predict_entities(text, self.labels, threshold=0.4)
        self.last_call_ms = int((time.perf_counter() - t0) * 1000)
        return _dedup_spans(ents)


def _dedup_spans(ents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group GLiNER raw spans by label, dedup-by-lowercased-text keeping the
    highest-score occurrence per label. Output preserves the original
    character offsets so the UI can mark up the source text."""
    by_label: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for e in ents:
        label = e["label"]
        text = e["text"]
        key = text.lower()
        score = float(e.get("score", 0.0))
        existing = by_label[label].get(key)
        if existing is None or score > existing["score"]:
            by_label[label][key] = {
                "text": text,
                "start": int(e.get("start", 0)),
                "end": int(e.get("end", 0)),
                "score": score,
            }
    return {label: list(spans.values()) for label, spans in by_label.items()}
