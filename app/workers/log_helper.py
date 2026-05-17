from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobLog


async def append_log(
    db: AsyncSession,
    run_table: str,
    run_id: int,
    line: str,
    level: str = "info",
) -> None:
    await db.execute(
        insert(JobLog).values(run_table=run_table, run_id=run_id, level=level, line=line)
    )
    await db.commit()
