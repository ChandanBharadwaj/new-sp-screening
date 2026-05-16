from __future__ import annotations

import time

import numpy as np

from app.config import settings


class Embedder:
    """Wraps BAAI/bge-small-en-v1.5 (or whatever EMBEDDER_MODEL points to)."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        t0 = time.perf_counter()
        self.model = SentenceTransformer(settings.embedder_model, device="cpu")
        self.load_time_ms = int((time.perf_counter() - t0) * 1000)
        self.dim = self.model.get_sentence_embedding_dimension()
        self.last_call_ms: int | None = None

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        t0 = time.perf_counter()
        out = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=32,
        )
        self.last_call_ms = int((time.perf_counter() - t0) * 1000)
        return out
