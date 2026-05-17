"""arq job: run_eval_job — execute the eval harness from the UI.

Persistence: `EvalRun` is written by the existing eval runner. We add an
`EvalJob` row to track worker state (running/success/failed + lifetime
timestamps + error_message) and back-fill its `eval_run_id` when the runner
completes successfully.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.models import EvalJob
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log
from app.workers.log_helper import append_log
from eval.runners.run_eval import run as run_eval


async def _new_job(classifier: str, split: str, limit: int | None) -> int:
    async with SessionLocal() as db:
        job = EvalJob(status="running", classifier=classifier, split=split, limit_n=limit)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return int(job.id)


async def _finish_job(job_id: int, **fields: Any) -> None:
    async with SessionLocal() as db:
        job = await db.get(EvalJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        job.finished_at = datetime.now(UTC)
        await db.commit()


async def run_eval_job(ctx: dict, params: dict[str, Any]) -> dict:
    configure_logging()
    params = params or {}
    classifier = str(params.get("classifier", "pipeline"))
    split = str(params.get("split", "test"))
    limit_raw = params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "", "null") else None
    except (TypeError, ValueError):
        limit = None

    job_id = await _new_job(classifier, split, limit)
    log.info("eval_job.start", job_id=job_id, classifier=classifier, split=split, limit=limit)

    async def emit(msg: str) -> None:
        async with SessionLocal() as db:
            await append_log(db, "eval_job", job_id, msg)

    await emit(f"Starting eval: classifier={classifier} split={split} limit={limit}")

    try:
        report = await run_eval(
            classifier=classifier,
            split=split,
            limit=limit,
            log_fn=emit,
        )
        eval_run_id = report.get("eval_run_id")
        await _finish_job(job_id, status="success", eval_run_id=eval_run_id)
        await emit(f"Persisted eval_run id={eval_run_id}. Done.")
        return {"status": "ok", "job_id": job_id, "eval_run_id": eval_run_id}
    except Exception as e:
        log.error("eval_job.failed", job_id=job_id, error=str(e))
        await emit(f"FAILED: {e}")
        await _finish_job(job_id, status="failed", error_message=str(e)[:2000])
        return {"status": "failed", "job_id": job_id, "error": str(e)}
