from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import HsCode

router = APIRouter(prefix="/api/v1/hs", tags=["hs"])


def _serialize(c: HsCode) -> dict[str, Any]:
    return {
        "code": c.code,
        "level": c.level,
        "chapter": c.chapter,
        "parent_code": c.parent_code,
        "title": c.title,
        "description": c.description,
        "chapter_notes": c.chapter_notes,
        "section_notes": c.section_notes,
    }


@router.get("/search")
async def search_hs(
    db: Annotated[AsyncSession, Depends(db_session)],
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=100),
) -> dict[str, Any]:
    stmt = (
        select(HsCode)
        .where(HsCode.title.ilike(f"%{q}%"))
        .order_by(HsCode.level, HsCode.code)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_serialize(r) for r in rows]}


@router.get("/tree")
async def tree_root(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rows = (
        await db.execute(select(HsCode).where(HsCode.level == 2).order_by(HsCode.code))
    ).scalars().all()
    return {"items": [_serialize(r) for r in rows]}


@router.get("/{code}")
async def get_hs(code: str, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    row = (await db.execute(select(HsCode).where(HsCode.code == code))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "hs code not found")
    children = (
        await db.execute(select(HsCode).where(HsCode.parent_code == code).order_by(HsCode.code))
    ).scalars().all()
    return {**_serialize(row), "children": [_serialize(c) for c in children]}
