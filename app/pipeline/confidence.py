"""Confidence metrics and abstention heuristic.

`compute(...)` returns the historical confidence dict (unchanged).

`compute_abstention(...)` decides whether the engine should signal low confidence
on a screening. Spec C2 forbids a categorical disposition (CLEAR/REVIEW/BLOCK), so
the surface here is intentionally narrow: `{abstained, reason, fallback_level}`.
Downstream systems decide what to do with it.

Tunable thresholds are stable defaults; calibration against eval gold splits is
follow-up work.
"""
from __future__ import annotations

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


def compute_abstention(
    candidates: list[dict],
    confidence: dict,
    *,
    top1_threshold: float = 0.45,
    gap_threshold: float = 0.05,
    chapter_consensus_floor: float = 0.40,
) -> dict:
    """Return `{abstained, reason, fallback_level}`.

    Cases:
      - empty candidates                              ⇒ abstain, reason=no_candidates, fallback=None
      - top1 < top1_threshold                         ⇒ abstain, reason=low_top1
                                                        fallback=4 if chapter_consensus high else 2
      - top1 ok but top1-top2 < gap_threshold AND
        chapter_consensus < chapter_consensus_floor   ⇒ abstain, reason=ambiguous_chapter, fallback=2
      - else                                          ⇒ confident
    """
    if not candidates:
        return {"abstained": True, "reason": "no_candidates", "fallback_level": None}

    top1 = float(confidence.get("top1_score", 0.0))
    gap = float(confidence.get("top1_minus_top2", 0.0))
    chapter_consensus = float(confidence.get("chapter_consensus", 0.0))

    if top1 < top1_threshold:
        fallback = 4 if chapter_consensus >= chapter_consensus_floor else 2
        return {"abstained": True, "reason": "low_top1", "fallback_level": fallback}

    if gap < gap_threshold and chapter_consensus < chapter_consensus_floor:
        return {"abstained": True, "reason": "ambiguous_chapter", "fallback_level": 2}

    return {"abstained": False, "reason": None, "fallback_level": None}


_LEVEL_LABEL = {2: "chapter", 4: "heading", 6: "subheading"}


def fallback_candidate(candidates: list[dict], fallback_level: int | None) -> dict | None:
    """Walk the top candidate's HS code to the requested aggregation level.

    Pure code-prefix; assumes 2/4/6-digit HS codes. Returns a candidate-shaped dict
    that callers (assemble.build) can drop into `hs_classification.fallback_candidate`.

    If the top candidate's code is already shorter than the requested fallback level
    (e.g. a 4-digit heading + fallback_level=6), the prefix and the label are clamped
    to the actual prefix length rather than mislabeling a heading as a subheading.
    """
    if not candidates or not fallback_level or fallback_level not in (2, 4, 6):
        return None
    top = candidates[0]
    code = (top.get("hs_code") or "")
    if not code:
        return None
    # Clamp to the prefix actually available on the top candidate.
    actual_level = min(fallback_level, len(code))
    if actual_level not in _LEVEL_LABEL:
        # Code length isn't one of 2/4/6 — bail rather than emit a fractional prefix.
        return None
    prefix = code[:actual_level]
    return {
        "hs_code": prefix,
        "level": _LEVEL_LABEL[actual_level],
        "chapter": code[:2] if code else None,
        "heading": code[:4] if len(code) >= 4 else None,
        "title": top.get("title") or "",
        "score": round(float(top.get("score", 0.0)), 4),
        "score_components": top.get("score_components", {}),
        "derived_from_top1": top.get("hs_code"),
    }
