import asyncio
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, models
from app.db.models import ScreeningRule
from app.models.registry import ModelRegistry
from app.pipeline.normalize import normalize
from app.pipeline.rules import _combine, _eval_conditions, _phrases_for
from app.schemas.rule import RuleIn, RuleOut, RuleTestIn, RuleTestOut

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


def _serialize(r: ScreeningRule) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "phrase": r.phrase,
        "phrase_group": r.phrase_group,
        "threshold": float(r.threshold),
        "conditions": r.conditions,
        "origin_iso": r.origin_iso,
        "destination_iso": r.destination_iso,
        "active": r.active,
        "version": r.version,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


async def _embed_phrase(reg: ModelRegistry, phrase: str) -> list[float]:
    vec = await asyncio.to_thread(reg.embedder.encode_one, phrase)
    return vec.tolist()


def _phrase_group_to_json(body: RuleIn) -> dict[str, Any] | None:
    if body.phrase_group is None:
        return None
    return {"mode": body.phrase_group.mode, "phrases": list(body.phrase_group.phrases)}


@router.get("")
async def list_rules(
    db: Annotated[AsyncSession, Depends(db_session)],
    active_only: bool = False,
) -> dict[str, Any]:
    stmt = select(ScreeningRule).order_by(ScreeningRule.id.desc())
    if active_only:
        stmt = stmt.where(ScreeningRule.active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_serialize(r) for r in rows]}


@router.post("", response_model=RuleOut)
async def create_rule(
    body: RuleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    reg: Annotated[ModelRegistry, Depends(models)],
) -> dict[str, Any]:
    emb = await _embed_phrase(reg, body.phrase)
    rule = ScreeningRule(
        name=body.name,
        phrase=body.phrase,
        phrase_group=_phrase_group_to_json(body),
        threshold=body.threshold,
        conditions=body.conditions,
        origin_iso=body.origin_iso,
        destination_iso=body.destination_iso,
        active=body.active,
        version=1,
        created_by=body.created_by,
        embedding=emb,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _serialize(rule)


@router.get("/{rule_id}")
async def get_rule(rule_id: int, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rule = (await db.execute(select(ScreeningRule).where(ScreeningRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "rule not found")
    history = (
        await db.execute(
            select(ScreeningRule)
            .where(ScreeningRule.name == rule.name)
            .order_by(ScreeningRule.version.desc())
        )
    ).scalars().all()
    return {
        **_serialize(rule),
        "history": [_serialize(h) for h in history],
    }


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: int,
    body: RuleIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    reg: Annotated[ModelRegistry, Depends(models)],
) -> dict[str, Any]:
    current = (
        await db.execute(select(ScreeningRule).where(ScreeningRule.id == rule_id))
    ).scalar_one_or_none()
    if not current:
        raise HTTPException(404, "rule not found")
    # Deactivate previous version; insert new version row.
    current.active = False
    emb = await _embed_phrase(reg, body.phrase)
    new = ScreeningRule(
        name=body.name,
        phrase=body.phrase,
        phrase_group=_phrase_group_to_json(body),
        threshold=body.threshold,
        conditions=body.conditions,
        origin_iso=body.origin_iso,
        destination_iso=body.destination_iso,
        active=body.active,
        version=(current.version or 1) + 1,
        created_by=body.created_by,
        embedding=emb,
    )
    db.add(new)
    await db.commit()
    await db.refresh(new)
    return _serialize(new)


@router.delete("/{rule_id}")
async def deactivate_rule(
    rule_id: int, db: Annotated[AsyncSession, Depends(db_session)]
) -> dict[str, Any]:
    rule = (
        await db.execute(select(ScreeningRule).where(ScreeningRule.id == rule_id))
    ).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "rule not found")
    rule.active = False
    await db.commit()
    return {"id": rule_id, "active": False}


@router.post("/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(
    rule_id: int,
    body: RuleTestIn,
    db: Annotated[AsyncSession, Depends(db_session)],
    reg: Annotated[ModelRegistry, Depends(models)],
) -> dict[str, Any]:
    rule = (
        await db.execute(select(ScreeningRule).where(ScreeningRule.id == rule_id))
    ).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "rule not found")
    norm = normalize(body.cargo_text)
    phrases, mode = _phrases_for(rule)
    scores = await asyncio.to_thread(reg.reranker.score_pairs, norm, phrases)
    sims = [_sigmoid(s) for s in scores]
    sim = _combine(sims, mode)
    ok = _eval_conditions(
        rule.conditions,
        {
            "shipment_value": body.shipment_value,
            "currency": body.currency,
            "metadata": body.metadata,
        },
    )
    per_phrase = [
        {"phrase": p, "similarity": round(s, 4)} for p, s in zip(phrases, sims, strict=True)
    ]
    return {
        "phrase_similarity": round(float(sim), 4),
        "threshold": float(rule.threshold),
        "delta_above_threshold": round(float(sim) - float(rule.threshold), 4),
        "conditions_satisfied": bool(ok),
        "mode": mode,
        "per_phrase": per_phrase,
    }


@router.post("/test-phrase")
async def test_phrase(
    body: dict[str, Any],
    reg: Annotated[ModelRegistry, Depends(models)],
) -> dict[str, Any]:
    """Test a draft phrase against sample text before saving the rule."""
    phrase = body.get("phrase")
    cargo_text = body.get("cargo_text")
    threshold = float(body.get("threshold", 0.5))
    if not phrase or not cargo_text:
        raise HTTPException(400, "phrase and cargo_text required")
    norm = normalize(cargo_text)
    scores = await asyncio.to_thread(reg.reranker.score_pairs, norm, [phrase])
    sim = _sigmoid(scores[0]) if scores else 0.0
    return {
        "phrase_similarity": round(float(sim), 4),
        "threshold": threshold,
        "delta_above_threshold": round(float(sim) - threshold, 4),
    }
