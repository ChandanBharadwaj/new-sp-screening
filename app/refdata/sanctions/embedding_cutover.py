"""Atomic embedder-generation cutover / rollback for sanctioned_commodity (item 1).

After embedding_v2 is fully backfilled and the parity gate passes, flip the active
generation in a single transaction; readers pick up the new column on the next
request boundary (EmbeddingGenerationCache TTL / NOTIFY). Rollback is the inverse
single UPDATE — keep the v1 column + index for >=30 days before dropping.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.embedding_generation import invalidate_embedding_cache
from app.telemetry import log

_TABLE = "sanctioned_commodity"


async def _set_active(db: AsyncSession, column: str, model: str) -> None:
    await db.execute(
        text(
            "UPDATE embedding_generation "
            "SET active_column = :col, active_model = :model, effective_from = now() "
            "WHERE table_name = :t"
        ),
        {"col": column, "model": model, "t": _TABLE},
    )
    # Wake any LISTEN-based consumers; the poll-based cache also converges on TTL.
    await db.execute(text("NOTIFY embedding_generation_changed, :p").bindparams(p=_TABLE))
    await db.commit()
    invalidate_embedding_cache()


async def cutover(db: AsyncSession, target_model: str) -> dict:
    """Make embedding_v2 the active generation. Refuses if any current row lacks it."""
    missing = (
        await db.execute(
            text(
                "SELECT count(*) FROM sanctioned_commodity "
                "WHERE embedding_v2 IS NULL AND sys_to IS NULL"
            )
        )
    ).scalar_one()
    if missing:
        return {"status": "blocked", "reason": "backfill_incomplete", "missing": int(missing)}
    await _set_active(db, "embedding_v2", target_model)
    log.info("embedding_cutover.done", active_column="embedding_v2", model=target_model)
    return {"status": "ok", "active_column": "embedding_v2", "active_model": target_model}


async def rollback(db: AsyncSession, model: str = "BAAI/bge-small-en-v1.5") -> dict:
    """Revert the active generation to the original `embedding` column."""
    await _set_active(db, "embedding", model)
    log.info("embedding_cutover.rollback", active_column="embedding", model=model)
    return {"status": "ok", "active_column": "embedding", "active_model": model}
