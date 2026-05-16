from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session

router = APIRouter(prefix="/api/v1/dashboards", tags=["dashboards"])


@router.get("/chapter-volume")
async def chapter_volume(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                """
                SELECT (hs_candidates -> 'top_candidates' -> 0 ->> 'chapter') AS chapter,
                       COUNT(*) AS n
                FROM screening_result
                WHERE hs_candidates IS NOT NULL
                GROUP BY 1
                ORDER BY n DESC
                """
            )
        )
    ).all()
    return {"items": [{"chapter": c or "?", "count": int(n)} for c, n in rows]}


@router.get("/sanction-hits-by-source")
async def sanction_hits_by_source(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                """
                SELECT item ->> 'source' AS source, COUNT(*) AS n
                FROM screening_result sr,
                     jsonb_array_elements(COALESCE(sr.sanction_matches -> 'items', '[]'::jsonb)) AS item
                WHERE item ->> 'source' IS NOT NULL
                GROUP BY 1
                ORDER BY n DESC
                """
            )
        )
    ).all()
    return {"items": [{"source": s, "count": int(n)} for s, n in rows]}


@router.get("/country-pair-heatmap")
async def country_pair_heatmap(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                """
                SELECT s.origin_iso AS o, s.destination_iso AS d, COUNT(*) AS n
                FROM screening_result r
                JOIN shipment s ON s.id = r.shipment_id
                GROUP BY 1, 2
                """
            )
        )
    ).all()
    return {
        "cells": [
            {"origin_iso": o or "?", "destination_iso": d or "?", "count": int(n)}
            for o, d, n in rows
        ]
    }


@router.get("/score-histograms")
async def score_histograms(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    """Bucketed top-1 score histogram from screening_result."""
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    width_bucket(
                        ((hs_candidates -> 'top_candidates' -> 0 ->> 'score')::float),
                        0, 1, 10
                    ) AS bucket,
                    COUNT(*) AS n
                FROM screening_result
                WHERE hs_candidates -> 'top_candidates' -> 0 ->> 'score' IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """
            )
        )
    ).all()
    return {
        "top1_score": [
            {"bucket": int(b) if b is not None else 0, "count": int(n)} for b, n in rows
        ]
    }


@router.get("/override-rate-trend")
async def override_rate_trend(db: AsyncSession = Depends(db_session)) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    (r.hs_candidates -> 'top_candidates' -> 0 ->> 'chapter') AS chapter,
                    COUNT(*) FILTER (WHERE fe.event_type = 'hs_corrected') AS corrections,
                    COUNT(*) AS total
                FROM screening_result r
                LEFT JOIN feedback_event fe ON fe.result_id = r.id
                GROUP BY 1
                """
            )
        )
    ).all()
    return {
        "items": [
            {
                "chapter": c or "?",
                "corrections": int(cr),
                "total": int(t),
                "rate": float(cr) / float(t) if t else 0.0,
            }
            for c, cr, t in rows
        ]
    }
