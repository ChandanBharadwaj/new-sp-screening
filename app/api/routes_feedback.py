from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import FeedbackEvent, ScreeningResult

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class FeedbackIn(BaseModel):
    result_id: UUID
    event_type: str  # hs_corrected | sanction_dismissed | rule_dismissed | escalated
    before_value: dict[str, Any] | None = None
    after_value: dict[str, Any] | None = None
    notes: str | None = None
    analyst_id: str | None = None


@router.post("")
async def create_feedback(body: FeedbackIn, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    res = (
        await db.execute(select(ScreeningResult).where(ScreeningResult.id == body.result_id))
    ).scalar_one_or_none()
    if not res:
        raise HTTPException(404, "result not found")
    ev = FeedbackEvent(
        result_id=body.result_id,
        event_type=body.event_type,
        before_value=body.before_value,
        after_value=body.after_value,
        notes=body.notes,
        analyst_id=body.analyst_id,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return {"id": ev.id, "created_at": ev.created_at.isoformat() if ev.created_at else None}


@router.get("/{result_id}")
async def list_for_result(result_id: UUID, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(FeedbackEvent)
            .where(FeedbackEvent.result_id == result_id)
            .order_by(FeedbackEvent.created_at.desc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "before_value": r.before_value,
                "after_value": r.after_value,
                "notes": r.notes,
                "analyst_id": r.analyst_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
