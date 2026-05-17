"""Compute the version stamp for every screening result.

Two parts:
- Static "what code/model is running": engine_version + embedder/reranker/NER
  identifiers + a SHA-256 hash of the LTR booster file. Cached at app startup.
- Per-request "what refdata snapshot was live when we screened": the latest
  successful RefdataRun.finished_at per source.

The static part is computed once via `compute_static()` and stashed on
`app.state.versions`. The per-request part is computed by `refdata_snapshot()`
against the request's DB session.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import RefdataRun


def _sha256_file(path: str) -> str | None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def compute_static() -> dict[str, Any]:
    """Snapshot of the running code / model artifacts."""
    return {
        "engine": settings.engine_version,
        "embedder": settings.embedder_model,
        "reranker": settings.reranker_model,
        "ner": settings.ner_model,
        "ltr_path": settings.ltr_model_path,
        "ltr_hash": _sha256_file(settings.ltr_model_path),
    }


async def refdata_snapshot(db: AsyncSession) -> dict[str, str]:
    """Latest successful RefdataRun.finished_at per source, ISO-formatted."""
    rows = (
        await db.execute(
            select(RefdataRun.source, func.max(RefdataRun.finished_at))
            .where(RefdataRun.status == "success")
            .group_by(RefdataRun.source)
        )
    ).all()
    return {src: ts.isoformat() for src, ts in rows if ts is not None}


async def build(db: AsyncSession, static: dict[str, Any]) -> dict[str, Any]:
    snap = await refdata_snapshot(db)
    return {**static, "refdata": snap}
