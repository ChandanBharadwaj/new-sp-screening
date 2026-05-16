from __future__ import annotations

import time

from app.config import settings


class Reranker:
    """Wraps a cross-encoder (BAAI/bge-reranker-v2-m3 by default)."""

    def __init__(self) -> None:
        from sentence_transformers import CrossEncoder

        t0 = time.perf_counter()
        self.model = CrossEncoder(settings.reranker_model, device="cpu", max_length=256)
        self.load_time_ms = int((time.perf_counter() - t0) * 1000)
        self.last_call_ms: int | None = None

    def score_pairs(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        pairs = [(query, c) for c in candidates]
        t0 = time.perf_counter()
        scores = self.model.predict(pairs, batch_size=16, show_progress_bar=False)
        self.last_call_ms = int((time.perf_counter() - t0) * 1000)
        return [float(s) for s in scores]
