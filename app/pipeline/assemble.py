from collections import Counter
from typing import Any
from uuid import UUID

from app.config import settings


def _level_label(level: int | None, code: str) -> str:
    if level == 2:
        return "chapter"
    if level == 4:
        return "heading"
    if level == 6:
        return "subheading"
    if code:
        return {2: "chapter", 4: "heading", 6: "subheading"}.get(len(code), "subheading")
    return "subheading"


def _candidate_view(c: dict) -> dict:
    code = c.get("hs_code", "")
    return {
        "hs_code": code,
        "level": _level_label(c.get("level"), code),
        "chapter": c.get("chapter") or (code[:2] if code else None),
        "heading": code[:4] if code and len(code) >= 4 else None,
        "title": c.get("title") or c.get("description") or "",
        "score": c.get("score", 0.0),
        "score_components": c.get("score_components", {}),
    }


def build(
    shipment_id: UUID,
    candidates: list[dict],
    entities: dict[str, list[str]],
    confidence: dict,
    latency: dict[str, int],
    top_n: int = 10,
    abstention: dict | None = None,
    fallback: dict | None = None,
    multi_commodity: list[dict] | None = None,
    versions: dict | None = None,
) -> dict[str, Any]:
    top = candidates[:top_n]
    out_candidates = [_candidate_view(c) for c in top]

    chapter_mass: Counter[str] = Counter()
    for c in top:
        ch = c.get("chapter") or (c.get("hs_code", "")[:2])
        if ch:
            chapter_mass[ch] += max(c.get("score", 0.0), 0.0)
    total = sum(chapter_mass.values()) or 1.0
    chapter_distribution = {k: round(v / total, 4) for k, v in chapter_mass.most_common(10)}

    abstention = abstention or {"abstained": False, "reason": None, "fallback_level": None}
    multi_view = (
        [_candidate_view(c) for c in multi_commodity] if multi_commodity else None
    )

    return {
        "shipment_id": str(shipment_id),
        "engine_version": settings.engine_version,
        "hs_classification": {
            "top_candidates": out_candidates,
            "chapter_distribution": chapter_distribution,
            "confidence_metrics": confidence,
            "abstained": bool(abstention.get("abstained")),
            "abstain_reason": abstention.get("reason"),
            "fallback_level": abstention.get("fallback_level"),
            "fallback_candidate": fallback,
            "multi_commodity": multi_view,
        },
        "sanction_matches": [],
        "rule_matches": [],
        "extracted_entities": entities,
        "latency_ms": latency,
        "versions": versions,
    }
