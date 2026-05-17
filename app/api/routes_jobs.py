"""SSE log streaming for long-running jobs (refdata, training, eval).

Workers append `JobLog` rows; this endpoint tails them by id and pushes each
new line as an SSE event. The stream terminates a moment after the
corresponding run row leaves the `running` state, so EventSource clients
auto-close gracefully.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.db.models import EvalJob, JobLog, RefdataRun, TrainingRun
from app.db.session import SessionLocal

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

# Mapping the URL slug to the ORM class — keeps the user-facing surface
# explicit and prevents arbitrary-table polling.
RUN_MODELS: dict[str, type] = {
    "refdata_run": RefdataRun,
    "training_run": TrainingRun,
    "eval_job": EvalJob,
}


async def _status_for(db: AsyncSession, run_table: str, run_id: int) -> str | None:
    model = RUN_MODELS[run_table]
    row = await db.get(model, run_id)
    return None if row is None else row.status


async def _fetch_new_logs(
    db: AsyncSession, run_table: str, run_id: int, after_id: int
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(JobLog)
            .where(
                JobLog.run_table == run_table,
                JobLog.run_id == run_id,
                JobLog.id > after_id,
            )
            .order_by(JobLog.id)
            .limit(500)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "ts": r.ts.isoformat() if r.ts else None,
            "level": r.level,
            "line": r.line,
        }
        for r in rows
    ]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _event_stream(
    request: Request, run_table: str, run_id: int
) -> AsyncIterator[str]:
    # Validate up-front so a 404 surfaces synchronously.
    async with SessionLocal() as db:
        status = await _status_for(db, run_table, run_id)
    if status is None:
        # Send one SSE error and close so the client gets a clear signal.
        yield _sse("error", {"message": f"unknown {run_table} {run_id}"})
        return

    # Initial sync. SSE comment as a keep-alive marker so proxies don't
    # buffer the first response.
    yield ": connected\n\n"
    after_id = 0
    idle_terminal_grace = 0  # tick count after the run row left "running"

    while True:
        if await request.is_disconnected():
            return

        async with SessionLocal() as db:
            new_logs = await _fetch_new_logs(db, run_table, run_id, after_id)
            current_status = await _status_for(db, run_table, run_id)

        for entry in new_logs:
            after_id = entry["id"]
            yield _sse("log", entry)

        if current_status and current_status != "running":
            # Drain any last-written logs in the next tick, then close.
            if not new_logs:
                idle_terminal_grace += 1
                if idle_terminal_grace >= 2:
                    yield _sse("done", {"status": current_status})
                    return
            else:
                idle_terminal_grace = 0
        else:
            idle_terminal_grace = 0

        await asyncio.sleep(0.5)


@router.get("/{run_table}/{run_id}/stream")
async def stream_logs(run_table: str, run_id: int, request: Request) -> StreamingResponse:
    if run_table not in RUN_MODELS:
        raise HTTPException(404, f"unknown run_table {run_table!r}")
    return StreamingResponse(
        _event_stream(request, run_table, run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{run_table}/{run_id}/logs")
async def get_logs(run_table: str, run_id: int) -> dict[str, Any]:
    """Non-streaming fallback — returns all logs for the run."""
    if run_table not in RUN_MODELS:
        raise HTTPException(404, f"unknown run_table {run_table!r}")
    async with SessionLocal() as db:
        rows = await _fetch_new_logs(db, run_table, run_id, after_id=0)
        status = await _status_for(db, run_table, run_id)
    return {"run_table": run_table, "run_id": run_id, "status": status, "logs": rows}
