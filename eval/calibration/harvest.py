"""Harvest per-query confidence features for calibration (item 3).

Runs the screening pipeline once over each labeled example and records the ranking
features the abstention gate uses, plus whether top1 matched the known HS code. The
post_hoc sweep then operates entirely on this table (no pipeline re-runs).
"""
from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.models.registry import load_models
from app.pipeline.orchestrator import run_screen
from app.pipeline.policy import PolicySnapshot
from app.telemetry import log


def _record_from_payload(payload: dict, gold_code: str) -> dict[str, Any]:
    hs = payload["hs_classification"]
    cm = hs.get("confidence_metrics", {})
    cands = hs.get("top_candidates", [])
    top1 = cands[0] if cands else {}
    comps = top1.get("score_components", {})
    pred = top1.get("hs_code") or ""
    return {
        "gold_hs_code": gold_code,
        "pred_hs_code": pred,
        "was_top1_correct": bool(pred == gold_code),
        "top1_score": float(cm.get("top1_score") or 0.0),
        "gap": float(cm.get("top1_minus_top2") or 0.0),
        "entropy": float(cm.get("entropy_topk") or 0.0),
        "chapter_consensus": float(cm.get("chapter_consensus") or 0.0),
        "dense": float(comps.get("dense") or 0.0),
        "cross_encoder": float(comps.get("cross_encoder") or 0.0),
        "abstained": bool(hs.get("abstained")),
    }


async def harvest(
    examples: list[dict],
    *,
    models=None,
    policy_override: PolicySnapshot | None = None,
) -> list[dict]:
    """Run the pipeline over `examples` ({description, hs_code, ...}); return feature rows.

    `policy_override` lets the retrieval-threshold sweep harvest under trial values.
    """
    models = models or load_models()
    rows: list[dict] = []
    async with SessionLocal() as db:
        for i, ex in enumerate(examples):
            payload = await run_screen(
                db=db,
                models=models,
                commodity_text=ex["description"],
                cargo_text=None,
                policy_override=policy_override,
            )
            rows.append({**_record_from_payload(payload, ex["hs_code"]), "kind": ex.get("kind", "real")})
            if (i + 1) % 50 == 0:
                log.info("calibration.harvest.progress", done=i + 1, total=len(examples))
    return rows
