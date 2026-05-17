from app.config import settings
from app.models.reranker import Reranker


def _candidate_text(c: dict) -> str:
    # Surface the HS code + chapter to the cross-encoder so it has a structured
    # anchor (the encoder sees `"HS 854231 (ch 85): memory ICs. ..."` instead of
    # plain prose). Helps disambiguate where multiple candidates share keywords.
    code = c.get("hs_code") or ""
    chapter = c.get("chapter") or ""
    title = c.get("title") or ""
    description = c.get("description") or ""
    if description == title:
        description = ""
    head = f"HS {code} (ch {chapter}):" if code else "HS:"
    body_parts = [p for p in (title, description) if p]
    if not body_parts:
        body_parts = ["(no description)"]
    return f"{head} {' '.join(body_parts)}"


def _retrieval_score(c: dict) -> float:
    # In RRF mode we want the cross-encoder to see the RRF top-K — RRF scores
    # live in a different (much smaller) numerical range than dense cosine, so
    # we can't blend them with max(); we pick one. In max mode we fall back to
    # the legacy per-source max-blend.
    if settings.fusion_mode == "rrf":
        return float(c.get("rrf_score", 0.0))
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
