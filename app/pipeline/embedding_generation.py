"""Active embedding-column resolver (item 1).

The embedder↔stored-vector contract is versioned: each table records which vector
column and model are authoritative in `embedding_generation`. Retrieval reads the
active column name from here so an embedder swap is a single transactional flip of
that row (after backfilling the new column and passing the parity gate).

The column name is interpolated into raw ANN SQL, so it is validated against a
fixed whitelist — it is never user-derived. Same TTL-poll design as PolicyCache
(app/pipeline/policy.py); LISTEN/NOTIFY can be layered on later for lower latency.
"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmbeddingGeneration

# Only these physical columns may be activated; guards the raw-SQL interpolation.
ALLOWED_COLUMNS = {"embedding", "embedding_v2"}
_DEFAULT = ("embedding", "BAAI/bge-small-en-v1.5")
_TTL_S = 30.0


class _Cache:
    def __init__(self) -> None:
        self._by_table: dict[str, tuple[str, str]] = {}
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self, db: AsyncSession) -> None:
        rows = (
            await db.execute(
                select(
                    EmbeddingGeneration.table_name,
                    EmbeddingGeneration.active_column,
                    EmbeddingGeneration.active_model,
                )
            )
        ).all()
        mapping: dict[str, tuple[str, str]] = {}
        for table_name, col, model in rows:
            if col not in ALLOWED_COLUMNS:
                raise ValueError(f"embedding_generation.active_column {col!r} not in {ALLOWED_COLUMNS}")
            mapping[table_name] = (col, model)
        self._by_table = mapping
        self._loaded_at = time.monotonic()

    async def active(self, db: AsyncSession, table_name: str) -> tuple[str, str]:
        """Return (column, model) active for `table_name`, refreshing on TTL expiry."""
        if (time.monotonic() - self._loaded_at) >= _TTL_S or table_name not in self._by_table:
            async with self._lock:
                if (time.monotonic() - self._loaded_at) >= _TTL_S or table_name not in self._by_table:
                    await self._refresh(db)
        return self._by_table.get(table_name, _DEFAULT)

    def invalidate(self) -> None:
        self._loaded_at = 0.0


_cache = _Cache()


async def active_embedding(db: AsyncSession, table_name: str = "sanctioned_commodity") -> tuple[str, str]:
    return await _cache.active(db, table_name)


def invalidate_embedding_cache() -> None:
    _cache.invalidate()
