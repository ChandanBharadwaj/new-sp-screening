"""Editable ship-gate thresholds backed by the `threshold` table.

Seeded on first access from `eval/ci/thresholds.yaml`. The YAML stays the
canonical CI gate (read by `eval.ci.compare`); the DB copy is what the
Status page renders and what operators edit from the UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import Threshold

router = APIRouter(prefix="/api/v1/thresholds", tags=["thresholds"])

YAML_PATH = Path(__file__).resolve().parents[2] / "eval" / "ci" / "thresholds.yaml"


def _yaml_seed() -> dict[str, float]:
    if not YAML_PATH.exists():
        return {}
    data = yaml.safe_load(YAML_PATH.read_text()) or {}
    return {str(k): float(v) for k, v in data.items()}


async def _ensure_seeded(db: AsyncSession) -> None:
    existing = (await db.execute(select(Threshold.key))).scalars().all()
    if existing:
        return
    seed = _yaml_seed()
    for k, v in seed.items():
        await db.execute(insert(Threshold).values(key=k, value=v, source="yaml_seed"))
    await db.commit()


async def get_all(db: AsyncSession) -> dict[str, float]:
    """Helper for other routes (e.g. routes_status) — returns thresholds dict."""
    await _ensure_seeded(db)
    rows = (await db.execute(select(Threshold))).scalars().all()
    return {r.key: float(r.value) for r in rows}


class ThresholdIn(BaseModel):
    key: str
    value: float


@router.get("")
async def list_thresholds(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    await _ensure_seeded(db)
    rows = (await db.execute(select(Threshold).order_by(Threshold.key))).scalars().all()
    return {
        "thresholds": [
            {
                "key": r.key,
                "value": float(r.value),
                "source": r.source,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "yaml_seed": _yaml_seed(),
    }


@router.put("")
async def upsert_threshold(body: ThresholdIn, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    await _ensure_seeded(db)
    existing = await db.get(Threshold, body.key)
    if existing is None:
        await db.execute(insert(Threshold).values(key=body.key, value=body.value, source="ui"))
    else:
        await db.execute(
            update(Threshold)
            .where(Threshold.key == body.key)
            .values(value=body.value, source="ui")
        )
    await db.commit()
    return {"key": body.key, "value": body.value, "source": "ui"}


@router.post("/reset")
async def reset_to_yaml(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    """Overwrite all UI-edited thresholds with the YAML seed values."""
    seed = _yaml_seed()
    if not seed:
        raise HTTPException(404, f"no YAML seed at {YAML_PATH}")
    for k, v in seed.items():
        existing = await db.get(Threshold, k)
        if existing is None:
            await db.execute(insert(Threshold).values(key=k, value=v, source="yaml_seed"))
        else:
            await db.execute(
                update(Threshold).where(Threshold.key == k).values(value=v, source="yaml_seed")
            )
    await db.commit()
    return {"reset": list(seed.keys())}
