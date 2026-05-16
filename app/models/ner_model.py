from __future__ import annotations

import time
from collections import defaultdict

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
    """Wraps GLiNER for customs entity extraction."""

    def __init__(self, labels: list[str] | None = None) -> None:
        from gliner import GLiNER

        t0 = time.perf_counter()
        self.model = GLiNER.from_pretrained(settings.ner_model)
        self.load_time_ms = int((time.perf_counter() - t0) * 1000)
        self.labels = labels or CUSTOMS_LABELS
        self.last_call_ms: int | None = None

    def predict(self, text: str) -> dict[str, list[str]]:
        t0 = time.perf_counter()
        ents = self.model.predict_entities(text, self.labels, threshold=0.4)
        self.last_call_ms = int((time.perf_counter() - t0) * 1000)
        out: dict[str, list[str]] = defaultdict(list)
        for e in ents:
            out[e["label"]].append(e["text"].lower())
        return {k: list(dict.fromkeys(v)) for k, v in out.items()}
