from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import CountryRule, SanctionedCommodity

router = APIRouter(prefix="/api/v1/sanctions", tags=["sanctions"])


@router.get("/sources")
async def list_sources(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(SanctionedCommodity.source, func.count())
            .group_by(SanctionedCommodity.source)
            .order_by(func.count().desc())
        )
    ).all()
    return {"sources": [{"source": s, "count": int(n)} for s, n in rows]}


@router.get("/by-country-pair")
async def by_country_pair(
    db: Annotated[AsyncSession, Depends(db_session)],
    origin: str | None = None,
    destination: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                """
                SELECT sc.id, sc.source, sc.source_record_id, sc.description,
                       sc.hs_codes, sc.restriction_type, sc.provenance_url,
                       cr.origin_iso, cr.destination_iso
                FROM sanctioned_commodity sc
                JOIN country_rule cr ON cr.sanctioned_commodity_id = sc.id
                WHERE cr.active = true
                  AND sc.sys_to IS NULL
                  AND (cr.origin_iso IS NULL OR cr.origin_iso = :origin OR :origin IS NULL)
                  AND (cr.destination_iso IS NULL OR cr.destination_iso = :destination OR :destination IS NULL)
                ORDER BY sc.source, sc.source_record_id
                LIMIT :limit
                """
            ),
            {"origin": origin, "destination": destination, "limit": limit},
        )
    ).mappings().all()
    return {
        "items": [
            {
                "id": r["id"],
                "source": r["source"],
                "source_record_id": r["source_record_id"],
                "description": r["description"],
                "hs_codes": list(r["hs_codes"] or []),
                "restriction_type": r["restriction_type"],
                "provenance_url": r["provenance_url"],
                "origin_iso": r["origin_iso"],
                "destination_iso": r["destination_iso"],
            }
            for r in rows
        ]
    }


@router.get("/heatmap")
async def heatmap(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                CountryRule.origin_iso,
                CountryRule.destination_iso,
                func.count(),
            )
            .where(CountryRule.active.is_(True))
            .group_by(CountryRule.origin_iso, CountryRule.destination_iso)
        )
    ).all()
    cells = [
        {
            "origin_iso": o or "*",
            "destination_iso": d or "*",
            "count": int(n),
        }
        for o, d, n in rows
    ]
    return {"cells": cells}


@router.get("/{sanction_id}")
async def get_sanction(sanction_id: int, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    row = (
        await db.execute(select(SanctionedCommodity).where(SanctionedCommodity.id == sanction_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "sanctioned commodity not found")
    rules = (
        await db.execute(select(CountryRule).where(CountryRule.sanctioned_commodity_id == sanction_id))
    ).scalars().all()
    return {
        "id": row.id,
        "source": row.source,
        "source_record_id": row.source_record_id,
        "description": row.description,
        "hs_codes": list(row.hs_codes or []),
        "restriction_type": row.restriction_type,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "provenance_url": row.provenance_url,
        "country_rules": [
            {
                "id": cr.id,
                "origin_iso": cr.origin_iso,
                "destination_iso": cr.destination_iso,
                "restriction_type": cr.restriction_type,
                "conditions": cr.conditions,
                "active": cr.active,
            }
            for cr in rules
        ],
    }
