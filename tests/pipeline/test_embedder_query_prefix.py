"""Embedder.encode_query attaches the BGE-small instruction prefix.

We don't load the actual model in unit tests (it's a 100MB download). Instead
we stub the encoder to a deterministic function and assert that:

  - encode_query prepends the documented BGE prefix
  - encode_one does NOT prepend the prefix
  - the toggle settings.embedder_use_query_prefix=False disables it
"""
from __future__ import annotations

import numpy as np
import pytest

from app.config import settings
from app.models.embedder import Embedder

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class _StubSentenceTransformer:
    """Drop-in replacement for sentence_transformers.SentenceTransformer."""

    def __init__(self, *_args, **_kwargs):
        self.captured: list[list[str]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts, **_kwargs) -> np.ndarray:
        self.captured.append(list(texts))
        return np.zeros((len(texts), 4), dtype=np.float32)


@pytest.fixture
def stub_embedder(monkeypatch) -> Embedder:
    import sentence_transformers as st

    monkeypatch.setattr(st, "SentenceTransformer", _StubSentenceTransformer)
    return Embedder()


def test_encode_query_uses_bge_prefix(stub_embedder: Embedder) -> None:
    stub_embedder.encode_query("memory ICs")
    last_batch = stub_embedder.model.captured[-1]
    assert last_batch == [BGE_QUERY_PREFIX + "memory ICs"]


def test_encode_one_does_not_prefix(stub_embedder: Embedder) -> None:
    stub_embedder.encode_one("memory ICs")
    last_batch = stub_embedder.model.captured[-1]
    assert last_batch == ["memory ICs"]
    assert BGE_QUERY_PREFIX not in last_batch[0]


def test_toggle_disables_prefix(stub_embedder: Embedder, monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedder_use_query_prefix", False)
    stub_embedder.encode_query("memory ICs")
    last_batch = stub_embedder.model.captured[-1]
    assert last_batch == ["memory ICs"]
