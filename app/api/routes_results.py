from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import ScreeningResult, Shipment

router = APIRouter(prefix="/api/v1/results", tags=["results"])


@router.get("")
async def list_results(
    db: AsyncSession = Depends(db_session),
    limit: int = Query(50, le=500),
    offset: int = 0,
    chapter: str | None = None,
    min_score: float | None = None,
    origin_iso: str | None = None,
    destination_iso: str | None = None,
) -> dict[str, Any]:
    stmt = select(ScreeningResult, Shipment).join(Shipment, Shipment.id == ScreeningResult.shipment_id).order_by(ScreeningResult.created_at.desc())
    if origin_iso:
        stmt = stmt.where(Shipment.origin_iso == origin_iso)
    if destination_iso:
        stmt = stmt.where(Shipment.destination_iso == destination_iso)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    items = []
    for res, ship in rows:
        top_candidates = (res.hs_candidates or {}).get("top_candidates", [])
        top1 = top_candidates[0] if top_candidates else {}
        top1_chapter = top1.get("chapter")
        top1_score = top1.get("score")
        if chapter and top1_chapter != chapter:
            continue
        if min_score is not None and (top1_score is None or top1_score < min_score):
            continue
        items.append(
            {
                "result_id": str(res.id),
                "shipment_id": str(ship.id),
                "external_ref": ship.external_ref,
                "commodity_text": ship.commodity_text,
                "origin_iso": ship.origin_iso,
                "destination_iso": ship.destination_iso,
                "top1_hs_code": top1.get("hs_code"),
                "top1_chapter": top1_chapter,
                "top1_score": top1_score,
                "engine_version": res.engine_version,
                "created_at": res.created_at.isoformat() if res.created_at else None,
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{result_id}")
async def get_result(result_id: UUID, db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    res = (await db.execute(select(ScreeningResult).where(ScreeningResult.id == result_id))).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "result not found")
    ship = (await db.execute(select(Shipment).where(Shipment.id == res.shipment_id))).scalar_one_or_none()
    return {
        "result_id": str(res.id),
        "shipment_id": str(res.shipment_id),
        "engine_version": res.engine_version,
        "shipment": {
            "commodity_text": ship.commodity_text if ship else None,
            "cargo_text": ship.cargo_text if ship else None,
            "origin_iso": ship.origin_iso if ship else None,
            "destination_iso": ship.destination_iso if ship else None,
        },
        "hs_classification": res.hs_candidates,
        "sanction_matches": (res.sanction_matches or {}).get("items", []),
        "rule_matches": (res.rule_matches or {}).get("items", []),
        "extracted_entities": res.extracted_entities,
        "confidence_metrics": res.confidence_metrics,
        "latency_ms": res.latency_ms,
        "created_at": res.created_at.isoformat() if res.created_at else None,
    }
