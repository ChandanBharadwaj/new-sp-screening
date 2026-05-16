import csv
import io
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.db.models import BatchJob, Shipment

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

REQUIRED_COLUMNS = {"commodity_text"}


@router.post("/upload")
async def upload(
    file: UploadFile,
    db: AsyncSession = Depends(db_session),
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

    shipment_ids: list[UUID] = []
    for row in reader:
        ship = Shipment(
            external_ref=row.get("external_ref"),
            commodity_text=row["commodity_text"],
            cargo_text=row.get("cargo_text"),
            origin_iso=(row.get("origin_iso") or None),
            destination_iso=(row.get("destination_iso") or None),
        )
        db.add(ship)
        await db.flush()
        shipment_ids.append(ship.id)

    job.total_rows = len(shipment_ids)
    job.status = "running"
    await db.commit()

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        for sid in shipment_ids:
            await pool.enqueue_job("screen_one", str(sid), str(job_id))
    finally:
        await pool.close()

    return {"batch_id": str(job_id), "total_rows": len(shipment_ids), "status": "running"}


@router.get("/{batch_id}")
async def get_batch(batch_id: UUID, db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
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
