"""arq job: train_ltr — build the LTR dataset and fit the booster.

Mirrors the refdata job pattern: creates a `training_run` row, streams
human-readable log lines into `job_log` so the UI's SSE endpoint can tail them,
and finalizes status/metrics on the row when done.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.models import TrainingRun
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log
from app.training.ltr_dataset import build_dataset
from app.training.ltr_train import fit_booster
from app.workers.log_helper import append_log


async def _new_run(params: dict[str, Any]) -> int:
    async with SessionLocal() as db:
        run = TrainingRun(kind="ltr", status="running", params=params)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return int(run.id)


async def _finish_run(run_id: int, **fields: Any) -> None:
    async with SessionLocal() as db:
        run = await db.get(TrainingRun, run_id)
        if run is None:
            return
        for k, v in fields.items():
            setattr(run, k, v)
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()


async def train_ltr(ctx: dict, params: dict[str, Any]) -> dict:
    """Worker entrypoint. Returns a status dict; UI polls
    /api/v1/training/runs and tails /api/v1/jobs/training_run/{id}/stream."""
    configure_logging()
    params = params or {}
    gold = Path(params.get("gold", "eval/gold/splits/train.jsonl"))
    dataset_csv = Path(params.get("dataset_csv", "artifacts/ltr_train.csv"))
    artifact = Path(params.get("artifact", "artifacts/ltr.txt"))
    limit = params.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = None

    run_id = await _new_run(
        {
            "gold": str(gold),
            "dataset_csv": str(dataset_csv),
            "artifact": str(artifact),
            "limit": limit,
        }
    )
    log.info("training_job.start", run_id=run_id, params=params)

    # Each log writes from its own short-lived session so the SSE poller sees
    # them committed promptly.
    async def emit(msg: str) -> None:
        async with SessionLocal() as db:
            await append_log(db, "training_run", run_id, msg)

    await emit(f"Starting LTR training (gold={gold}, limit={limit})")

    try:
        await emit("Phase 1/2: building feature dataset from gold split")
        ds = await build_dataset(gold, dataset_csv, limit, log_fn=emit)
        await emit(
            f"Dataset built: {ds['n_queries']} queries, "
            f"{ds['n_rows']} candidate rows → {ds['out_path']}"
        )

        await emit("Phase 2/2: fitting LightGBM lambdarank booster")
        # fit_booster is sync but heavy; run it in a thread so we don't block
        # the arq event loop and the SSE poller stays responsive.
        loop = asyncio.get_running_loop()
        fit_result = await loop.run_in_executor(
            None,
            lambda: fit_booster(dataset_csv, artifact, log_fn=None),
        )
        await emit(
            f"Booster trained: {fit_result['n_rows']} rows, "
            f"training_time_ms={fit_result['training_time_ms']}, "
            f"ndcg={fit_result['ndcg']}"
        )
        metrics = {
            "dataset": {"n_queries": ds["n_queries"], "n_rows": ds["n_rows"]},
            "training_time_ms": fit_result["training_time_ms"],
            "ndcg": fit_result["ndcg"],
        }
        await _finish_run(
            run_id,
            status="success",
            dataset_csv_path=str(dataset_csv),
            artifact_path=str(artifact),
            metrics=metrics,
        )
        await emit("Done.")
        return {"status": "ok", "run_id": run_id, "artifact": str(artifact), "metrics": metrics}
    except Exception as e:
        log.error("training_job.failed", run_id=run_id, error=str(e))
        await emit(f"FAILED: {e}")
        await _finish_run(run_id, status="failed", error_message=str(e)[:2000])
        return {"status": "failed", "run_id": run_id, "error": str(e)}
