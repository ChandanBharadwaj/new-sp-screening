import csv
import io
from typing import Annotated, Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._batch_export import serialize_errors_csv
from app.api.deps import db_session
from app.config import settings
from app.db.models import BatchJob, BatchJobError, Shipment

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

REQUIRED_COLUMNS = {"commodity_text"}


@router.post("/upload")
async def upload(
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    raw = await file.read()
    text_buf = io.StringIO(raw.decode("utf-8-sig", errors="replace"))
    reader = csv.DictReader(text_buf)
    if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise HTTPException(400, f"CSV must include columns: {sorted(REQUIRED_COLUMNS)}")

    job = BatchJob(filename=file.filename, status="pending", total_rows=0)
    db.add(job)
    await db.flush()
    job_id = job.id

    # (row_index, shipment_id) — row_index is the CSV row number (0-based,
    # after the header) so operators can find the bad row in their source file.
    shipments: list[tuple[int, UUID]] = []
    for idx, row in enumerate(reader):
        ship = Shipment(
            external_ref=row.get("external_ref"),
            commodity_text=row["commodity_text"],
            cargo_text=row.get("cargo_text"),
            origin_iso=(row.get("origin_iso") or None),
            destination_iso=(row.get("destination_iso") or None),
        )
        db.add(ship)
        await db.flush()
        shipments.append((idx, ship.id))

    job.total_rows = len(shipments)
    job.status = "running"
    await db.commit()

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        for idx, sid in shipments:
            await pool.enqueue_job("screen_one", str(sid), str(job_id), idx)
    finally:
        await pool.close()

    return {"batch_id": str(job_id), "total_rows": len(shipments), "status": "running"}


@router.get("/{batch_id}")
async def get_batch(batch_id: UUID, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    row = (await db.execute(select(BatchJob).where(BatchJob.id == batch_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "batch not found")
    return {
        "batch_id": str(row.id),
        "filename": row.filename,
        "status": row.status,
        "total_rows": row.total_rows,
        "completed_rows": row.completed_rows,
        "failed_rows": row.failed_rows,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{batch_id}/errors")
async def list_batch_errors(
    batch_id: UUID,
    db: Annotated[AsyncSession, Depends(db_session)],
    limit: int = Query(200, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    total = (
        await db.execute(
            select(func.count(BatchJobError.id)).where(BatchJobError.batch_id == batch_id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(BatchJobError)
            .where(BatchJobError.batch_id == batch_id)
            .order_by(BatchJobError.row_index.asc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "row_index": r.row_index,
                "raw_row": r.raw_row,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{batch_id}/errors.csv")
async def download_batch_errors_csv(
    batch_id: UUID,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> StreamingResponse:
    rows = (
        await db.execute(
            select(BatchJobError)
            .where(BatchJobError.batch_id == batch_id)
            .order_by(BatchJobError.row_index.asc())
        )
    ).scalars().all()
    body = serialize_errors_csv(list(rows))
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="batch_{batch_id}_errors.csv"'
        },
    )
