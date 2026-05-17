"""Data browser endpoints — surface every ingested table for the UI.

The Admin page handles ingestion control; this module powers a unified Data
viewer (training examples, shipments, eval runs, files on disk) so the
operator never has to drop to a shell to inspect what landed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import EvalRun, HsTrainingExample, RefdataRun, Shipment

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/training-examples")
async def list_training_examples(
    db: Annotated[AsyncSession, Depends(db_session)],
    source: str | None = None,
    q: str | None = None,
    chapter: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(HsTrainingExample).order_by(HsTrainingExample.id.desc())
    count_stmt = select(func.count()).select_from(HsTrainingExample)
    if source:
        stmt = stmt.where(HsTrainingExample.source == source)
        count_stmt = count_stmt.where(HsTrainingExample.source == source)
    if q:
        stmt = stmt.where(HsTrainingExample.description.ilike(f"%{q}%"))
        count_stmt = count_stmt.where(HsTrainingExample.description.ilike(f"%{q}%"))
    if chapter:
        stmt = stmt.where(HsTrainingExample.hs_code.like(f"{chapter}%"))
        count_stmt = count_stmt.where(HsTrainingExample.hs_code.like(f"{chapter}%"))
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()

    by_source_rows = (
        await db.execute(
            select(HsTrainingExample.source, func.count()).group_by(HsTrainingExample.source)
        )
    ).all()
    by_source = {s: int(n) for s, n in by_source_rows}

    return {
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "source_id": r.source_id,
                "description": r.description,
                "hs_code": r.hs_code,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "by_source": by_source,
    }


@router.get("/shipments")
async def list_shipments(
    db: Annotated[AsyncSession, Depends(db_session)],
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(Shipment).order_by(Shipment.created_at.desc())
    count_stmt = select(func.count()).select_from(Shipment)
    if q:
        stmt = stmt.where(Shipment.commodity_text.ilike(f"%{q}%"))
        count_stmt = count_stmt.where(Shipment.commodity_text.ilike(f"%{q}%"))
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "external_ref": r.external_ref,
                "commodity_text": r.commodity_text,
                "cargo_text": r.cargo_text,
                "origin_iso": r.origin_iso,
                "destination_iso": r.destination_iso,
                "shipment_value": float(r.shipment_value) if r.shipment_value is not None else None,
                "currency": r.currency,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/eval-runs")
async def list_eval_runs(
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: int = Query(50, le=500),
) -> dict[str, Any]:
    rows = (
        await db.execute(select(EvalRun).order_by(EvalRun.ran_at.desc()).limit(limit))
    ).scalars().all()
    return {
        "items": [
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
                "n_examples": r.n_examples,
            }
            for r in rows
        ]
    }


@router.get("/refdata-runs")
async def list_refdata_runs(
    db: Annotated[AsyncSession, Depends(db_session)],
    source: str | None = None,
    limit: int = Query(50, le=500),
) -> dict[str, Any]:
    stmt = select(RefdataRun).order_by(RefdataRun.started_at.desc()).limit(limit)
    if source:
        stmt = stmt.where(RefdataRun.source == source)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "rows_upserted": r.rows_upserted,
                "status": r.status,
                "error_message": r.error_message,
                "notes": r.notes,
            }
            for r in rows
        ]
    }


@router.get("/files")
async def list_files() -> dict[str, Any]:
    """Walk ./data/ and list every cached source file with size & mtime."""
    root = Path("data")
    if not root.exists():
        return {"files": [], "root": str(root)}
    items: list[dict[str, Any]] = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            stat = f.stat()
            items.append(
                {
                    "path": str(f),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    total_bytes = sum(i["size_bytes"] for i in items)
    return {"files": items, "root": str(root), "total_files": len(items), "total_bytes": total_bytes}
