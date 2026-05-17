from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, cast, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import ScreeningResult, Shipment

router = APIRouter(prefix="/api/v1/results", tags=["results"])

# Risk score, computed in SQL so sort + pagination see the full result set.
#   max_sanction_similarity + 0.5 * max_rule_delta + 0.3 * (1 if abstained else 0)
# Coalesced to 0 when arrays are empty / fields missing.
_RISK_SQL = text(
    """
    COALESCE((
        SELECT MAX((item->>'similarity')::float)
        FROM jsonb_array_elements(coalesce(sanction_matches->'items', '[]'::jsonb)) AS item
    ), 0)
    + 0.5 * COALESCE((
        SELECT MAX((item->>'delta_above_threshold')::float)
        FROM jsonb_array_elements(coalesce(rule_matches->'items', '[]'::jsonb)) AS item
    ), 0)
    + 0.3 * CASE WHEN (hs_candidates->>'abstained')::boolean THEN 1 ELSE 0 END
    """
)


def _apply_filters(
    stmt,
    *,
    origin_iso: str | None,
    destination_iso: str | None,
    abstained: bool | None,
    has_sanctions: bool | None,
    has_rules: bool | None,
    since: datetime | None,
    chapter: str | None,
    min_score: float | None,
):
    if origin_iso:
        stmt = stmt.where(Shipment.origin_iso == origin_iso)
    if destination_iso:
        stmt = stmt.where(Shipment.destination_iso == destination_iso)
    if since:
        stmt = stmt.where(ScreeningResult.created_at >= since)
    if abstained is True:
        stmt = stmt.where(
            ScreeningResult.hs_candidates["abstained"].astext == "true"
        )
    elif abstained is False:
        stmt = stmt.where(
            or_(
                ScreeningResult.hs_candidates["abstained"].astext != "true",
                ScreeningResult.hs_candidates["abstained"].is_(None),
            )
        )
    if has_sanctions is True:
        stmt = stmt.where(
            func.jsonb_array_length(
                func.coalesce(
                    ScreeningResult.sanction_matches["items"],
                    cast(literal("[]"), ScreeningResult.sanction_matches.type),
                )
            )
            > 0
        )
    elif has_sanctions is False:
        stmt = stmt.where(
            func.coalesce(
                func.jsonb_array_length(
                    func.coalesce(
                        ScreeningResult.sanction_matches["items"],
                        cast(literal("[]"), ScreeningResult.sanction_matches.type),
                    )
                ),
                0,
            )
            == 0
        )
    if has_rules is True:
        stmt = stmt.where(
            func.jsonb_array_length(
                func.coalesce(
                    ScreeningResult.rule_matches["items"],
                    cast(literal("[]"), ScreeningResult.rule_matches.type),
                )
            )
            > 0
        )
    elif has_rules is False:
        stmt = stmt.where(
            func.coalesce(
                func.jsonb_array_length(
                    func.coalesce(
                        ScreeningResult.rule_matches["items"],
                        cast(literal("[]"), ScreeningResult.rule_matches.type),
                    )
                ),
                0,
            )
            == 0
        )
    if chapter:
        # Top1 chapter is in `hs_candidates.top_candidates[0].chapter`.
        stmt = stmt.where(
            ScreeningResult.hs_candidates["top_candidates"][0]["chapter"].astext
            == chapter
        )
    if min_score is not None:
        stmt = stmt.where(
            cast(
                ScreeningResult.hs_candidates["top_candidates"][0]["score"].astext,
                Float,
            )
            >= min_score
        )
    return stmt


@router.get("")
async def list_results(
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0, le=100_000),
    chapter: str | None = None,
    min_score: float | None = None,
    origin_iso: str | None = None,
    destination_iso: str | None = None,
    abstained: bool | None = None,
    has_sanctions: bool | None = None,
    has_rules: bool | None = None,
    since: datetime | None = None,
    sort: Literal["recent", "risk_desc", "confidence_asc"] = "recent",
) -> dict[str, Any]:
    base = select(ScreeningResult, Shipment).join(
        Shipment, Shipment.id == ScreeningResult.shipment_id
    )
    base = _apply_filters(
        base,
        origin_iso=origin_iso,
        destination_iso=destination_iso,
        abstained=abstained,
        has_sanctions=has_sanctions,
        has_rules=has_rules,
        since=since,
        chapter=chapter,
        min_score=min_score,
    )

    # Sort
    if sort == "risk_desc":
        base = base.order_by(_RISK_SQL.desc(), ScreeningResult.created_at.desc())
    elif sort == "confidence_asc":
        # Ascending confidence == lowest top1_score first; NULLs treated as 0.
        top1 = cast(
            ScreeningResult.confidence_metrics["top1_score"].astext, Float
        )
        base = base.order_by(
            func.coalesce(top1, 0.0).asc(), ScreeningResult.created_at.desc()
        )
    else:
        base = base.order_by(ScreeningResult.created_at.desc())

    # Count before pagination.
    count_stmt = select(func.count()).select_from(
        _apply_filters(
            select(ScreeningResult.id).join(
                Shipment, Shipment.id == ScreeningResult.shipment_id
            ),
            origin_iso=origin_iso,
            destination_iso=destination_iso,
            abstained=abstained,
            has_sanctions=has_sanctions,
            has_rules=has_rules,
            since=since,
            chapter=chapter,
            min_score=min_score,
        ).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    rows = (await db.execute(base.limit(limit).offset(offset))).all()
    items = []
    for res, ship in rows:
        hs = res.hs_candidates or {}
        top_candidates = hs.get("top_candidates", [])
        top1 = top_candidates[0] if top_candidates else {}
        sanctions = (res.sanction_matches or {}).get("items", [])
        rules = (res.rule_matches or {}).get("items", [])
        items.append(
            {
                "result_id": str(res.id),
                "shipment_id": str(ship.id),
                "external_ref": ship.external_ref,
                "commodity_text": ship.commodity_text,
                "origin_iso": ship.origin_iso,
                "destination_iso": ship.destination_iso,
                "top1_hs_code": top1.get("hs_code"),
                "top1_chapter": top1.get("chapter"),
                "top1_score": top1.get("score"),
                "abstained": bool(hs.get("abstained")),
                "abstain_reason": hs.get("abstain_reason"),
                "sanctions_count": len(sanctions),
                "max_sanction_similarity": (
                    max((s.get("similarity") or 0.0) for s in sanctions)
                    if sanctions
                    else 0.0
                ),
                "rules_count": len(rules),
                "max_rule_delta": (
                    max((r.get("delta_above_threshold") or 0.0) for r in rules)
                    if rules
                    else 0.0
                ),
                "engine_version": res.engine_version,
                "created_at": res.created_at.isoformat() if res.created_at else None,
            }
        )
    return {"items": items, "limit": limit, "offset": offset, "total": int(total)}


@router.get("/{result_id}")
async def get_result(
    result_id: UUID,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    res = (
        await db.execute(
            select(ScreeningResult).where(ScreeningResult.id == result_id)
        )
    ).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "result not found")
    ship = (
        await db.execute(select(Shipment).where(Shipment.id == res.shipment_id))
    ).scalar_one_or_none()
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
