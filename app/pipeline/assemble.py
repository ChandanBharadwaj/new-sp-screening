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


def build(
    shipment_id: UUID,
    candidates: list[dict],
    entities: dict[str, list[str]],
    confidence: dict,
    latency: dict[str, int],
    top_n: int = 10,
) -> dict[str, Any]:
    top = candidates[:top_n]
    out_candidates = []
    for c in top:
        code = c.get("hs_code", "")
        out_candidates.append(
            {
                "hs_code": code,
                "level": _level_label(c.get("level"), code),
                "chapter": c.get("chapter") or (code[:2] if code else None),
                "heading": code[:4] if code and len(code) >= 4 else None,
                "title": c.get("title") or c.get("description") or "",
                "score": c.get("score", 0.0),
                "score_components": c.get("score_components", {}),
            }
        )

    chapter_mass: Counter[str] = Counter()
    for c in top:
        ch = c.get("chapter") or (c.get("hs_code", "")[:2])
        if ch:
            chapter_mass[ch] += max(c.get("score", 0.0), 0.0)
    total = sum(chapter_mass.values()) or 1.0
    chapter_distribution = {k: round(v / total, 4) for k, v in chapter_mass.most_common(10)}

    return {
        "shipment_id": str(shipment_id),
        "engine_version": settings.engine_version,
        "hs_classification": {
            "top_candidates": out_candidates,
            "chapter_distribution": chapter_distribution,
            "confidence_metrics": confidence,
        },
        "sanction_matches": [],
        "rule_matches": [],
        "extracted_entities": entities,
        "latency_ms": latency,
    }
