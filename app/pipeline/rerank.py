import math

from app.config import settings
from app.models.reranker import Reranker

# Hard ceiling on how many candidates the cross-encoder scores per query, and the
# RRF-score gap below which neighbouring candidates count as one "plateau" that
# should be scored together rather than truncated mid-tie (item 5).
_CE_HARD_CAP = 50
_PLATEAU_EPS = 0.001


def _dense_proxy(c: dict) -> float:
    return max(float(c.get("dense_similarity", 0.0)), float(c.get("dense_via_training", 0.0)))


def _dynamic_head_k(scores: list[float], base_k: int) -> int:
    """Extend the rerank head past base_k across any flat RRF plateau, capped at 50.

    A fixed top-K truncation can split a run of near-identical RRF scores, denying
    the cross-encoder candidates that are statistically tied with ones it does see.
    """
    n = len(scores)
    k = min(base_k, n)
    while k < min(_CE_HARD_CAP, n) and (scores[k - 1] - scores[k]) < _PLATEAU_EPS:
        k += 1
    return k


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
    head_k = _dynamic_head_k([_retrieval_score(c) for c in candidates], settings.rerank_top_k)
    head = candidates[:head_k]
    tail = candidates[head_k:]
    texts = [_candidate_text(c) for c in head]
    scores = reranker.score_pairs(query, texts)
    # Cross-encoder logits — squash into [0,1] via sigmoid for downstream ease.
    sig = [1.0 / (1.0 + math.exp(-s)) for s in scores]
    for c, s in zip(head, sig, strict=True):
        c["cross_encoder_score"] = float(s)
        c["ce_was_evaluated"] = 1.0
    # Tail (beyond the cap) was NOT scored. Setting cross_encoder_score=0 would tell
    # the LTR "the cross-encoder judged this irrelevant", masking strong dense/sparse
    # signals. Instead flag it unevaluated and fall back to the dense proxy as the
    # expected cross-encoder value; the LTR's ce_was_evaluated feature lets it learn
    # to trust dense/sparse more here. (Production refinement: replace the proxy with
    # an offline-fit isotonic dense→ce mapping stored in policy_parameter.)
    for c in tail:
        c["ce_was_evaluated"] = 0.0
        c.setdefault("cross_encoder_score", _dense_proxy(c))
    return head + tail
