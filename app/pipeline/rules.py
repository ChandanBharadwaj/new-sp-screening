"""Semantic rule scoring stage.

Fetches active rules whose (origin_iso, destination_iso) scope matches the shipment,
scores the cross-encoder over (normalized cargo text, rule.phrase), evaluates the
small JSON conditions DSL, and returns per-rule quantitative results.

Phrase composition: when a rule sets `phrase_group = {"mode": "any_of" | "all_of",
"phrases": [...]}`, the cross-encoder scores each phrase and the rule's final
`phrase_similarity` is max() (any_of) or min() (all_of) over those. When
`phrase_group` is null, the legacy single `phrase` field is used.

Conditions DSL (all optional, evaluated as AND):
    {
      "min_value": 5000.0,                  # shipment.shipment_value >= 5000
      "max_value": 100000.0,
      "currency_in": ["USD", "EUR"],
      "metadata_eq": {"party_type": "broker"}
    }
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ScreeningRule
from app.models.reranker import Reranker


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _eval_conditions(cond: dict[str, Any] | None, shipment: dict[str, Any]) -> bool:
    if not cond:
        return True
    val = shipment.get("shipment_value")
    if "min_value" in cond and (val is None or val < cond["min_value"]):
        return False
    if "max_value" in cond and (val is None or val > cond["max_value"]):
        return False
    if "currency_in" in cond:
        cur = shipment.get("currency")
        if cur not in cond["currency_in"]:
            return False
    if "metadata_eq" in cond:
        meta = shipment.get("metadata") or {}
        for k, v in cond["metadata_eq"].items():
            if meta.get(k) != v:
                return False
    return True


def _phrases_for(rule: ScreeningRule) -> tuple[list[str], str]:
    """Return (phrases_to_score, mode) for a rule.

    mode is "single" | "any_of" | "all_of"; callers combine scores accordingly.
    """
    pg = rule.phrase_group
    if pg and pg.get("phrases"):
        mode = pg.get("mode") or "any_of"
        if mode not in ("any_of", "all_of"):
            mode = "any_of"
        phrases = [p for p in pg["phrases"] if p]
        if phrases:
            return phrases, mode
    return [rule.phrase], "single"


def _combine(per_phrase: list[float], mode: str) -> float:
    if not per_phrase:
        return 0.0
    if mode == "all_of":
        return min(per_phrase)
    # any_of and single both reduce to max() (single happens to have one element).
    return max(per_phrase)


async def score(
    *,
    db: AsyncSession,
    reranker: Reranker,
    cargo_text: str,
    origin_iso: str | None,
    destination_iso: str | None,
    shipment: dict[str, Any],
) -> list[dict]:
    stmt = select(ScreeningRule).where(
        ScreeningRule.active.is_(True),
        ((ScreeningRule.origin_iso.is_(None)) | (ScreeningRule.origin_iso == origin_iso)),
        (
            (ScreeningRule.destination_iso.is_(None))
            | (ScreeningRule.destination_iso == destination_iso)
        ),
    )
    rules = (await db.execute(stmt)).scalars().all()
    if not rules:
        return []

    # Flatten (rule_index, phrase) pairs so we can score them in a single batched
    # reranker call, then regroup.
    flat: list[tuple[int, str]] = []
    per_rule_modes: list[tuple[list[str], str]] = []
    for i, rule in enumerate(rules):
        phrases, mode = _phrases_for(rule)
        per_rule_modes.append((phrases, mode))
        for p in phrases:
            flat.append((i, p))

    if not flat:
        return []

    flat_phrases = [p for _, p in flat]
    cross_scores = await asyncio.to_thread(reranker.score_pairs, cargo_text, flat_phrases)
    sims = [_sigmoid(s) for s in cross_scores]

    # Regroup per-rule.
    by_rule: list[list[float]] = [[] for _ in rules]
    for (i, _), sim in zip(flat, sims, strict=True):
        by_rule[i].append(float(sim))

    out: list[dict] = []
    for rule, sims_for_rule, (phrases, mode) in zip(rules, by_rule, per_rule_modes, strict=True):
        sim = _combine(sims_for_rule, mode)
        ok = _eval_conditions(rule.conditions, shipment)
        per_phrase_view = [
            {"phrase": p, "similarity": round(s, 4)}
            for p, s in zip(phrases, sims_for_rule, strict=True)
        ]
        out.append(
            {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "phrase": rule.phrase,
                "phrase_similarity": round(float(sim), 4),
                "threshold": float(rule.threshold),
                "delta_above_threshold": round(float(sim) - float(rule.threshold), 4),
                "conditions_satisfied": bool(ok),
                "version": rule.version,
                "mode": mode,
                "per_phrase": per_phrase_view,
                "created_by": rule.created_by,
            }
        )
    out.sort(key=lambda r: r["phrase_similarity"], reverse=True)
    return out
