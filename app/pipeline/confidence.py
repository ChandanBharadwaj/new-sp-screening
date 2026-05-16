import math
from collections import Counter


def _normalize(scores: list[float]) -> list[float]:
    s = sum(max(x, 0.0) for x in scores)
    if s <= 0:
        return [0.0] * len(scores)
    return [max(x, 0.0) / s for x in scores]


def compute(candidates: list[dict], k: int = 10) -> dict:
    if not candidates:
        return {
            "top1_score": 0.0,
            "top1_minus_top2": 0.0,
            "entropy_topk": 0.0,
            "chapter_consensus": 0.0,
            "cross_source_agreement": False,
        }
    topk = candidates[:k]
    top1 = float(topk[0]["score"])
    top2 = float(topk[1]["score"]) if len(topk) > 1 else 0.0

    norm = _normalize([c["score"] for c in topk])
    entropy = -sum(p * math.log(p + 1e-12) for p in norm if p > 0)

    chapter_mass: Counter[str] = Counter()
    for c, p in zip(topk, norm, strict=True):
        if c.get("chapter"):
            chapter_mass[c["chapter"]] += p
    chapter_consensus = max(chapter_mass.values()) if chapter_mass else 0.0

    top = candidates[0]
    sc = top.get("score_components", {})
    cross_source_agreement = (
        sc.get("dense", 0) > 0.4
        and sc.get("sparse", 0) > 0.0
        and sc.get("cross_encoder", 0) > 0.4
    )

    return {
        "top1_score": round(top1, 4),
        "top1_minus_top2": round(top1 - top2, 4),
        "entropy_topk": round(entropy, 4),
        "chapter_consensus": round(float(chapter_consensus), 4),
        "cross_source_agreement": bool(cross_source_agreement),
    }
