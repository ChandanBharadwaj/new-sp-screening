from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RefdataRun
from app.db.session import SessionLocal
from app.telemetry import configure_logging, log
from app.workers.log_helper import append_log


@asynccontextmanager
async def with_run_logging(source: str, notes: str | None = None) -> AsyncIterator[tuple[AsyncSession, RefdataRun]]:
    configure_logging()
    async with SessionLocal() as db:
        run = RefdataRun(source=source, status="running", notes=notes)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        log.info("refdata.run.started", source=source, run_id=run.id)
        await append_log(db, "refdata_run", run.id, f"Started {source}")
        try:
            yield db, run
        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            await db.merge(run)
            await db.commit()
            await append_log(db, "refdata_run", run.id, f"FAILED: {e}", level="error")
            log.error("refdata.run.failed", source=source, run_id=run.id, error=str(e))
            raise
        else:
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            await db.merge(run)
            await db.commit()
            await append_log(
                db,
                "refdata_run",
                run.id,
                f"Success — rows_upserted={run.rows_upserted}",
            )
            log.info(
                "refdata.run.success",
                source=source,
                run_id=run.id,
                rows=run.rows_upserted,
            )


async def update_tsv_for_table(db: AsyncSession, table: str, columns: tuple[str, ...] = ("description", "title")) -> None:
    parts = [f"COALESCE({c}, '')" for c in columns]
    expr = " || ' ' || ".join(parts)
    await db.execute(
        text(
            f"""
            UPDATE {table}
            SET description_tsv = to_tsvector('english', {expr})
            WHERE description_tsv IS NULL
            """
        )
    )


def batches(items: list, size: int = 64):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def mark_progress(db: AsyncSession, run: RefdataRun, rows: int) -> None:
    """Update RefdataRun.rows_upserted mid-run so the UI can show progress.

    Also emits a JobLog line every 1000 rows so the SSE log panel reflects
    progress without flooding the table.
    """
    prev = run.rows_upserted or 0
    run.rows_upserted = rows
    await db.commit()
    if rows // 1000 != prev // 1000:
        await append_log(db, "refdata_run", run.id, f"…upserted {rows} rows")


def lazy_embedder():
    """Return the shared singleton Embedder (loaded once at app/worker startup)."""
    from app.models.registry import get_models

    return get_models().embedder
