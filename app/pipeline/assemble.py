from collections import Counter
from typing import Any
from uuid import UUID

from app.config import settings

# Materialized rules carry `created_by = "sanctions_source:<src>"`. Keyword-list
# rules additionally use the `KW:<list_name>` source convention; this prefix
# detects them inside the `created_by` value the rules-scoring stage echoes back.
_KEYWORD_LIST_CREATED_BY_PREFIX = "sanctions_source:KW:"


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


def group_rule_matches_by_list(rule_matches: list[dict]) -> list[dict]:
    """Group fired rule matches by keyword-list name for the result drill-down.

    A keyword-list rule has `created_by = "sanctions_source:KW:<list_name>"`. For
    each distinct list we surface the top-scoring phrase, the number of phrases
    that crossed their per-rule threshold, and the count of all rules from that
    list that fired (whether above or below threshold). Operator-authored rules
    and sanction-derived rules from OFAC/EU/etc. are ignored here — they have
    their own surface in `rule_matches`.

    Output is sorted by top_similarity desc.
    """
    by_list: dict[str, dict] = {}
    for m in rule_matches:
        created_by = m.get("created_by") or ""
        if not isinstance(created_by, str) or not created_by.startswith(
            _KEYWORD_LIST_CREATED_BY_PREFIX
        ):
            continue
        list_name = created_by[len(_KEYWORD_LIST_CREATED_BY_PREFIX):]
        sim = float(m.get("phrase_similarity", 0.0))
        thr = float(m.get("threshold", 0.0))
        above = bool(m.get("conditions_satisfied", True)) and sim >= thr
        bucket = by_list.setdefault(
            list_name,
            {
                "list": list_name,
                "top_phrase": m.get("phrase"),
                "top_similarity": sim,
                "n_above_threshold": 0,
                "n_total": 0,
            },
        )
        bucket["n_total"] += 1
        if above:
            bucket["n_above_threshold"] += 1
        if sim > bucket["top_similarity"]:
            bucket["top_similarity"] = sim
            bucket["top_phrase"] = m.get("phrase")
    out = list(by_list.values())
    out.sort(key=lambda r: r["top_similarity"], reverse=True)
    return out


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
