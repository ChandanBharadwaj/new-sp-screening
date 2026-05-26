"""arq entrypoint for the calibration pipeline (item 3) — UI/cron triggerable."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.telemetry import log
from eval.calibration.run import run_calibration


async def run_calibration_job(ctx: dict, params: dict[str, Any] | None = None) -> dict:
    params = params or {}
    gold = Path(params.get("gold", "eval/gold/splits/dev.jsonl"))
    log.info("calibration_job.start", gold=str(gold))
    res = await run_calibration(
        gold,
        per_record=int(params.get("per_record", 1)),
        coverage_floor=float(params.get("coverage_floor", 0.5)),
        retrieval_sample=int(params.get("retrieval_sample", 60)),
        apply=bool(params.get("apply", True)),
    )
    return {"status": "ok", "run_id": res["run_id"], "applied": res["applied"]}
