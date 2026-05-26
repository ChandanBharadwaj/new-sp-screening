from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models import BatchJob, BatchJobError, Shipment
from app.db.session import SessionLocal
from app.pipeline.orchestrator import run_screen
from app.pipeline.persistence import build_screening_result
from app.telemetry import log


async def screen_one(
    ctx: dict,
    shipment_id: str,
    batch_id: str,
    row_index: int = 0,
) -> dict:
    models = ctx["models"]
    sid = UUID(shipment_id)
    bid = UUID(batch_id)

    async with SessionLocal() as db:
        ship = (await db.execute(select(Shipment).where(Shipment.id == sid))).scalar_one_or_none()
        if not ship:
            log.warning("worker.shipment_missing", shipment_id=shipment_id)
            return {"status": "missing"}

        try:
            payload = await run_screen(
                db=db,
                models=models,
                commodity_text=ship.commodity_text,
                cargo_text=ship.cargo_text,
                origin_iso=ship.origin_iso,
                destination_iso=ship.destination_iso,
                shipment_value=float(ship.shipment_value) if ship.shipment_value is not None else None,
                currency=ship.currency,
                metadata=ship.metadata_json,
                shipment_id=sid,
                static_versions=ctx.get("versions_static"),
            )
            db.add(build_screening_result(sid, payload))

            job = (await db.execute(select(BatchJob).where(BatchJob.id == bid))).scalar_one_or_none()
            if job:
                job.completed_rows = (job.completed_rows or 0) + 1
                job.updated_at = datetime.now(UTC)
                if job.completed_rows + (job.failed_rows or 0) >= (job.total_rows or 0):
                    job.status = "done"
            await db.commit()
            return {"status": "ok"}
        except Exception as e:
            log.error("worker.screen_failed", shipment_id=shipment_id, error=str(e))
            # Reconstruct the original CSV row from the persisted Shipment fields so
            # operators can fix the source data and re-upload. row_index lets them
            # find the bad row in the original file.
            raw_row = {
                "external_ref": ship.external_ref,
                "commodity_text": ship.commodity_text,
                "cargo_text": ship.cargo_text,
                "origin_iso": ship.origin_iso,
                "destination_iso": ship.destination_iso,
            }
            db.add(
                BatchJobError(
                    batch_id=bid,
                    row_index=row_index,
                    raw_row=raw_row,
                    error_message=str(e),
                )
            )
            job = (await db.execute(select(BatchJob).where(BatchJob.id == bid))).scalar_one_or_none()
            if job:
                job.failed_rows = (job.failed_rows or 0) + 1
                job.updated_at = datetime.now(UTC)
                if (job.completed_rows or 0) + job.failed_rows >= (job.total_rows or 0):
                    job.status = "failed" if (job.completed_rows or 0) == 0 else "done"
            await db.commit()
            return {"status": "failed", "error": str(e)}
