from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.db.models import BatchJob, EvalRun, HsCode, HsTrainingExample, RefdataRun
from app.models.registry import model_status

router = APIRouter(prefix="/api/v1/status", tags=["status"])

_started_at = time.time()
THRESHOLDS_PATH = Path(__file__).resolve().parents[2] / "eval" / "ci" / "thresholds.yaml"

REFDATA_SOURCES = [
    {
        "source": "HTS",
        "command": "python -m app.refdata.hts.ingest --year 2025",
        "table": "hs_code",
    },
    {
        "source": "ScheduleB",
        "command": "python -m app.refdata.schedule_b.ingest --file ./data/schedule_b/schedule_b.csv",
        "table": "hs_training_example",
    },
    {
        "source": "CROSS",
        "command": "python -m app.refdata.cross.ingest",
        "table": "hs_training_example",
    },
]


def _load_thresholds() -> dict[str, float]:
    if not THRESHOLDS_PATH.exists():
        return {}
    return yaml.safe_load(THRESHOLDS_PATH.read_text()) or {}


@router.get("/system")
async def system_status(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    pg_ok = False
    try:
        await db.execute(text("SELECT 1"))
        pg_ok = True
    except Exception:
        pg_ok = False

    redis_ok = False
    try:
        from arq.connections import RedisSettings, create_pool

        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
        await pool.close()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "engine_version": settings.engine_version,
        "uptime_seconds": int(time.time() - _started_at),
        "postgres": {"reachable": pg_ok},
        "redis": {"reachable": redis_ok},
    }


@router.get("/models")
async def models_status() -> dict[str, Any]:
    return {"models": model_status()}


@router.get("/refdata")
async def refdata_status(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    hs_total = (await db.execute(select(func.count()).select_from(HsCode))).scalar_one()
    hs_by_level_rows = (
        await db.execute(select(HsCode.level, func.count()).group_by(HsCode.level))
    ).all()
    hs_by_level = {int(lvl): int(n) for lvl, n in hs_by_level_rows}

    train_total = (await db.execute(select(func.count()).select_from(HsTrainingExample))).scalar_one()
    train_by_source_rows = (
        await db.execute(
            select(HsTrainingExample.source, func.count()).group_by(HsTrainingExample.source)
        )
    ).all()
    train_by_source = {s: int(n) for s, n in train_by_source_rows}

    sources = []
    for s in REFDATA_SOURCES:
        last_run = (
            await db.execute(
                select(RefdataRun)
                .where(RefdataRun.source == s["source"])
                .order_by(RefdataRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if s["table"] == "hs_code":
            row_count = hs_total
        else:
            row_count = train_by_source.get(s["source"], 0)
        sources.append(
            {
                "source": s["source"],
                "command": s["command"],
                "last_run": {
                    "started_at": last_run.started_at.isoformat() if last_run and last_run.started_at else None,
                    "finished_at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
                    "rows_upserted": last_run.rows_upserted if last_run else None,
                    "status": last_run.status if last_run else "never_run",
                    "error_message": last_run.error_message if last_run else None,
                }
                if last_run
                else {"status": "never_run"},
                "row_count": int(row_count),
            }
        )

    return {
        "sources": sources,
        "totals": {
            "hs_code": int(hs_total),
            "hs_code_by_level": hs_by_level,
            "hs_training_example": int(train_total),
            "hs_training_example_by_source": train_by_source,
        },
    }


@router.get("/eval")
async def eval_status(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(select(EvalRun).order_by(EvalRun.ran_at.desc()).limit(20))
    ).scalars().all()
    runs = [
        {
            "id": r.id,
            "ran_at": r.ran_at.isoformat() if r.ran_at else None,
            "classifier": r.classifier,
            "split": r.split,
            "top1_subheading": r.top1_subheading,
            "top3_subheading": r.top3_subheading,
            "top1_chapter": r.top1_chapter,
            "mrr": r.mrr,
            "p50_ms": r.p50_ms,
            "p95_ms": r.p95_ms,
            "p99_ms": r.p99_ms,
            "n_examples": r.n_examples,
        }
        for r in rows
    ]
    thresholds = _load_thresholds()
    latest = next((r for r in runs if r["split"] == "test"), None)
    pass_fail = None
    if latest and thresholds:
        pass_fail = {
            "top1_subheading": (latest.get("top1_subheading") or 0) >= thresholds.get("top1_subheading", 0),
            "top3_subheading": (latest.get("top3_subheading") or 0) >= thresholds.get("top3_subheading", 0),
            "top1_chapter": (latest.get("top1_chapter") or 0) >= thresholds.get("top1_chapter", 0),
            "p95_ms": (latest.get("p95_ms") or 1e9) <= thresholds.get("p95_ms", 1000),
        }
    return {"runs": runs, "thresholds": thresholds, "latest_pass_fail": pass_fail}


@router.get("/batches")
async def batches_status(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(select(BatchJob).order_by(BatchJob.created_at.desc()).limit(10))
    ).scalars().all()
    return {
        "batches": [
            {
                "batch_id": str(r.id),
                "filename": r.filename,
                "status": r.status,
                "total_rows": r.total_rows,
                "completed_rows": r.completed_rows,
                "failed_rows": r.failed_rows,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }
