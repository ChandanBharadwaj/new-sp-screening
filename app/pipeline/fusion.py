from collections import Counter

from app.models.ltr import LtrRanker

LEVEL_DEPTH = {2: 2, 4: 4, 6: 6}


def _depth(c: dict) -> float:
    lvl = c.get("level")
    if lvl in LEVEL_DEPTH:
        return float(LEVEL_DEPTH[lvl])
    code = c.get("hs_code", "")
    return float(min(len(code), 6))


def _chapter_priors(candidates: list[dict]) -> dict[str, float]:
    chapters = [c.get("chapter") for c in candidates if c.get("chapter")]
    if not chapters:
        return {}
    counts = Counter(chapters)
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


def fuse(ltr: LtrRanker, candidates: list[dict], shipment) -> list[dict]:
    if not candidates:
        return []
    priors = _chapter_priors(candidates)

    # Pre-rerank ordering for the gap feature uses cross-encoder if present.
    sortable = sorted(
        candidates,
        key=lambda c: c.get("cross_encoder_score", 0.0),
        reverse=True,
    )
    top_score = sortable[0].get("cross_encoder_score", 0.0)
    second_score = sortable[1].get("cross_encoder_score", 0.0) if len(sortable) > 1 else 0.0
    gap = max(0.0, top_score - second_score)

    feats = []
    for c in candidates:
        feats.append(
            {
                "dense_similarity": max(c.get("dense_similarity", 0.0), c.get("dense_via_training", 0.0)),
                "sparse_score": c.get("sparse_score", 0.0),
                "entity_overlap_score": c.get("entity_overlap_score", 0.0),
                "cross_encoder_score": c.get("cross_encoder_score", 0.0),
                "chapter_prior": priors.get(c.get("chapter"), 0.0),
                "candidate_depth": _depth(c),
                "top1_minus_top2_gap": gap,
            }
        )

    final_scores = ltr.predict(feats)
    for c, f, s in zip(candidates, feats, final_scores, strict=True):
        c["score_components"] = {
            "dense": round(f["dense_similarity"], 4),
            "sparse": round(f["sparse_score"], 4),
            "entity_overlap": round(f["entity_overlap_score"], 4),
            "cross_encoder": round(f["cross_encoder_score"], 4),
            "chapter_prior": round(f["chapter_prior"], 4),
            "ltr_final": round(s, 4),
        }
        c["score"] = round(float(s), 4)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates
