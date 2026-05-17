from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.db.models import TrainingRun

router = APIRouter(prefix="/api/v1/training", tags=["training"])


class TrainLtrIn(BaseModel):
    gold: str | None = None
    dataset_csv: str | None = None
    artifact: str | None = None
    limit: int | None = None


def _run_to_dict(r: TrainingRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "error_message": r.error_message,
        "params": r.params,
        "artifact_path": r.artifact_path,
        "dataset_csv_path": r.dataset_csv_path,
        "metrics": r.metrics,
    }


@router.post("/ltr/run")
async def run_ltr(body: TrainLtrIn | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if body:
        for k in ("gold", "dataset_csv", "artifact", "limit"):
            v = getattr(body, k)
            if v is not None:
                params[k] = v
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job("train_ltr", params)
    finally:
        await pool.close()
    return {"enqueued_job_id": job.job_id if job else None, "params": params}


@router.get("/runs")
async def list_runs(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(select(TrainingRun).order_by(TrainingRun.started_at.desc()).limit(20))
    ).scalars().all()
    return {"runs": [_run_to_dict(r) for r in rows]}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    r = await db.get(TrainingRun, run_id)
    if r is None:
        raise HTTPException(404, "unknown training run")
    return _run_to_dict(r)
