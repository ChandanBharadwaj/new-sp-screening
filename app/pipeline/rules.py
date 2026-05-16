"""Semantic rule scoring stage.

Fetches active rules whose (origin_iso, destination_iso) scope matches the shipment,
scores the cross-encoder over (normalized cargo text, rule.phrase), evaluates the
small JSON conditions DSL, and returns per-rule quantitative results.

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

    phrases = [r.phrase for r in rules]
    cross_scores = await asyncio.to_thread(reranker.score_pairs, cargo_text, phrases)
    sims = [_sigmoid(s) for s in cross_scores]

    out: list[dict] = []
    for rule, sim in zip(rules, sims, strict=True):
        ok = _eval_conditions(rule.conditions, shipment)
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
            }
        )
    out.sort(key=lambda r: r["phrase_similarity"], reverse=True)
    return out
