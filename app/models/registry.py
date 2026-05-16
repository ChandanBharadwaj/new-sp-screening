from __future__ import annotations

from dataclasses import dataclass

from app.models.embedder import Embedder
from app.models.ltr import LtrRanker
from app.models.ner_model import NerModel
from app.models.reranker import Reranker
from app.telemetry import log


@dataclass
class ModelRegistry:
    embedder: Embedder
    reranker: Reranker
    ner: NerModel
    ltr: LtrRanker


_singleton: ModelRegistry | None = None


def load_models() -> ModelRegistry:
    global _singleton
    if _singleton is not None:
        return _singleton
    log.info("models.loading")
    embedder = Embedder()
    log.info("models.embedder_loaded", load_ms=embedder.load_time_ms, dim=embedder.dim)
    reranker = Reranker()
    log.info("models.reranker_loaded", load_ms=reranker.load_time_ms)
    ner = NerModel()
    log.info("models.ner_loaded", load_ms=ner.load_time_ms)
    ltr = LtrRanker()
    log.info("models.ltr_loaded", load_ms=ltr.load_time_ms, has_booster=ltr.booster is not None)
    _singleton = ModelRegistry(embedder=embedder, reranker=reranker, ner=ner, ltr=ltr)
    return _singleton


def get_models() -> ModelRegistry:
    if _singleton is None:
        return load_models()
    return _singleton


def model_status() -> list[dict]:
    if _singleton is None:
        return [
            {"name": n, "loaded": False, "load_time_ms": None, "last_call_ms": None}
            for n in ["embedder", "reranker", "ner", "ltr"]
        ]
    r = _singleton
    return [
        {
            "name": "embedder",
            "model_id": r.embedder.model.__class__.__name__,
            "loaded": True,
            "load_time_ms": r.embedder.load_time_ms,
            "last_call_ms": r.embedder.last_call_ms,
            "dim": r.embedder.dim,
        },
        {
            "name": "reranker",
            "model_id": r.reranker.model.__class__.__name__,
            "loaded": True,
            "load_time_ms": r.reranker.load_time_ms,
            "last_call_ms": r.reranker.last_call_ms,
        },
        {
            "name": "ner",
            "model_id": r.ner.model.__class__.__name__,
            "loaded": True,
            "load_time_ms": r.ner.load_time_ms,
            "last_call_ms": r.ner.last_call_ms,
            "labels": r.ner.labels,
        },
        {
            "name": "ltr",
            "loaded": r.ltr.booster is not None,
            "load_time_ms": r.ltr.load_time_ms,
            "fallback": r.ltr.booster is None,
            "feature_order": r.ltr.feature_order,
        },
    ]
