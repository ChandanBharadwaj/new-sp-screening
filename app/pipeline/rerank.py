from app.config import settings
from app.models.reranker import Reranker


def _candidate_text(c: dict) -> str:
    parts = []
    if c.get("title"):
        parts.append(c["title"])
    if c.get("description") and c.get("description") != c.get("title"):
        parts.append(c["description"])
    if not parts:
        parts.append(f"HS code {c.get('hs_code', '')}")
    return " | ".join(parts)


def _retrieval_score(c: dict) -> float:
    return max(
        c.get("dense_similarity", 0.0),
        c.get("dense_via_training", 0.0),
        c.get("sparse_score", 0.0),
        c.get("entity_overlap_score", 0.0),
    )


def rerank(reranker: Reranker, query: str, candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []
    candidates.sort(key=_retrieval_score, reverse=True)
    head = candidates[: settings.rerank_top_k]
    tail = candidates[settings.rerank_top_k :]
    texts = [_candidate_text(c) for c in head]
    scores = reranker.score_pairs(query, texts)
    # Cross-encoder logits — squash into [0,1] via sigmoid for downstream ease.
    import math

    sig = [1.0 / (1.0 + math.exp(-s)) for s in scores]
    for c, s in zip(head, sig, strict=True):
        c["cross_encoder_score"] = float(s)
    for c in tail:
        c.setdefault("cross_encoder_score", 0.0)
    return head + tail
