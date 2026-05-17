from __future__ import annotations

from typing import Annotated, Any

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.db.models import EvalJob

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


class EvalRunIn(BaseModel):
    classifier: str = "pipeline"
    split: str = "test"
    limit: int | None = None


def _job_to_dict(j: EvalJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "status": j.status,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "error_message": j.error_message,
        "classifier": j.classifier,
        "split": j.split,
        "limit_n": j.limit_n,
        "eval_run_id": j.eval_run_id,
    }


@router.post("/run")
async def run(body: EvalRunIn) -> dict[str, Any]:
    if body.split not in ("train", "dev", "test"):
        raise HTTPException(400, "split must be train|dev|test")
    if body.classifier not in ("pipeline", "baseline_noop"):
        raise HTTPException(400, "classifier must be pipeline|baseline_noop")
    params = {"classifier": body.classifier, "split": body.split, "limit": body.limit}
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job("run_eval_job", params)
    finally:
        await pool.close()
    return {"enqueued_job_id": job.job_id if job else None, "params": params}


@router.get("/jobs")
async def list_jobs(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rows = (
        await db.execute(select(EvalJob).order_by(EvalJob.started_at.desc()).limit(20))
    ).scalars().all()
    return {"jobs": [_job_to_dict(j) for j in rows]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    j = await db.get(EvalJob, job_id)
    if j is None:
        raise HTTPException(404, "unknown eval job")
    return _job_to_dict(j)
