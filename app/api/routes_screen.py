from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, models
from app.db.models import ScreeningResult, Shipment
from app.models.registry import ModelRegistry
from app.pipeline.orchestrator import run_screen
from app.schemas.screen import ShipmentIn

router = APIRouter(prefix="/api/v1", tags=["screen"])


async def _persist(db: AsyncSession, shipment_in: ShipmentIn, payload: dict[str, Any]) -> None:
    sid = payload["shipment_id"]
    ship = Shipment(
        id=sid,
        external_ref=shipment_in.external_ref,
        commodity_text=shipment_in.commodity_text,
        cargo_text=shipment_in.cargo_text,
        origin_iso=shipment_in.origin_iso,
        destination_iso=shipment_in.destination_iso,
        shipment_value=shipment_in.shipment_value,
        currency=shipment_in.currency,
        metadata_json=shipment_in.metadata,
    )
    db.add(ship)
    res = ScreeningResult(
        shipment_id=sid,
        hs_candidates=payload["hs_classification"],
        sanction_matches={"items": payload["sanction_matches"]},
        rule_matches={"items": payload["rule_matches"]},
        extracted_entities=payload["extracted_entities"],
        confidence_metrics=payload["hs_classification"]["confidence_metrics"],
        latency_ms=payload["latency_ms"],
        engine_version=payload["engine_version"],
        versions=payload.get("versions"),
    )
    db.add(res)
    await db.commit()


def _static_versions(request: Request) -> dict[str, Any] | None:
    return getattr(request.app.state, "versions_static", None)


@router.post("/screen")
async def screen(
    body: ShipmentIn,
    request: Request,
    db: AsyncSession = Depends(db_session),
    reg: ModelRegistry = Depends(models),
) -> dict[str, Any]:
    payload = await run_screen(
        db=db,
        models=reg,
        commodity_text=body.commodity_text,
        cargo_text=body.cargo_text,
        origin_iso=body.origin_iso,
        destination_iso=body.destination_iso,
        shipment_value=body.shipment_value,
        currency=body.currency,
        metadata=body.metadata,
        static_versions=_static_versions(request),
    )
    await _persist(db, body, payload)
    return payload


@router.post("/classify")
async def classify(
    body: ShipmentIn,
    request: Request,
    db: AsyncSession = Depends(db_session),
    reg: ModelRegistry = Depends(models),
) -> dict[str, Any]:
    payload = await run_screen(
        db=db,
        models=reg,
        commodity_text=body.commodity_text,
        cargo_text=body.cargo_text,
        origin_iso=body.origin_iso,
        destination_iso=body.destination_iso,
        shipment_value=body.shipment_value,
        currency=body.currency,
        metadata=body.metadata,
        static_versions=_static_versions(request),
    )
    return payload["hs_classification"]
