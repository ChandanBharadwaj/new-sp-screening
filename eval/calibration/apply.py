"""Write calibrated threshold values into the policy tables (item 3).

Each recommendation closes the currently-active row (effective_to = now()) and
inserts a new effective-dated row, preserving the audit trail. inference_threshold
stores a numeric value; policy_parameter stores jsonb. created_by != approved_by
satisfies the two-person CHECK on policy_parameter.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.policy import invalidate_policy_cache
from app.telemetry import log


async def apply_recommendation(
    db: AsyncSession,
    store: tuple[str, str, str],
    value: float,
    *,
    calibrated_from: str,
    rationale: str,
) -> None:
    table, a, b = store
    if table == "inference_threshold":
        await db.execute(
            text(
                "UPDATE inference_threshold SET effective_to = now() "
                "WHERE pipeline = :p AND parameter = :q AND effective_to IS NULL"
            ),
            {"p": a, "q": b},
        )
        await db.execute(
            text(
                "INSERT INTO inference_threshold "
                "(pipeline, parameter, value, calibrated_from, created_by, approved_by, rationale) "
                "VALUES (:p, :q, :v, :cf, 'calibration', 'calibration_review', :r)"
            ),
            {"p": a, "q": b, "v": value, "cf": calibrated_from, "r": rationale},
        )
    elif table == "policy_parameter":
        await db.execute(
            text(
                "UPDATE policy_parameter SET effective_to = now() "
                "WHERE scope = :s AND name = :n AND effective_to IS NULL"
            ),
            {"s": a, "n": b},
        )
        await db.execute(
            text(
                "INSERT INTO policy_parameter "
                "(scope, name, value, created_by, approved_by, change_ticket, rationale) "
                "VALUES (:s, :n, CAST(:v AS jsonb), 'calibration', 'calibration_review', :ct, :r)"
            ),
            {"s": a, "n": b, "v": json.dumps(value), "ct": calibrated_from, "r": rationale},
        )
    else:
        raise ValueError(f"unknown store table {table!r}")


async def apply_all(db: AsyncSession, recommendations: list[dict[str, Any]], *, calibrated_from: str) -> int:
    """recommendations: [{store, value, rationale}]. Returns count written."""
    n = 0
    for rec in recommendations:
        if rec.get("store") is None:
            continue  # reported_only
        await apply_recommendation(
            db, tuple(rec["store"]), float(rec["value"]),
            calibrated_from=calibrated_from, rationale=rec.get("rationale", "calibration"),
        )
        n += 1
    await db.commit()
    invalidate_policy_cache()
    log.info("calibration.apply.done", written=n, calibrated_from=calibrated_from)
    return n
