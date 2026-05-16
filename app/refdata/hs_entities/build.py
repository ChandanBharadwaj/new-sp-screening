"""Populate hs_entity_index by running GLiNER over every HS code's title+description.

USAGE:
    python -m app.refdata.hs_entities.build
    python -m app.refdata.hs_entities.build --level 6 --limit 100
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import HsCode, HsEntityIndex
from app.models.ner_model import NerModel
from app.refdata.common import mark_progress, with_run_logging
from app.telemetry import configure_logging, log


def _label_weight(label: str) -> float:
    weights = {
        "material": 1.0,
        "form": 0.8,
        "end_use": 0.9,
        "processing_state": 0.7,
        "composition_percentages": 0.5,
        "dimensions": 0.4,
    }
    return weights.get(label, 0.5)


async def main_async(level: int | None, limit: int | None) -> None:
    configure_logging()
    log.info("hs_entities.loading_ner")
    ner = NerModel()
    log.info("hs_entities.ner_loaded", load_ms=ner.load_time_ms)

    async with with_run_logging("HsEntityIndex", notes=f"level={level} limit={limit}") as (db, run):
        stmt = select(HsCode.code, HsCode.title, HsCode.description)
        if level is not None:
            stmt = stmt.where(HsCode.level == level)
        if limit:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).all()
        log.info("hs_entities.rows_to_process", n=len(rows))

        upserted = 0
        for idx, (code, title, description) in enumerate(rows):
            text = ((title or "") + ". " + (description or "")).strip()
            if not text:
                continue
            try:
                entities: dict[str, list[str]] = ner.predict(text)
            except Exception as e:
                log.warning("hs_entities.ner_failed", code=code, error=str(e))
                continue

            for etype, values in entities.items():
                for v in values:
                    if not v:
                        continue
                    stmt2: Any = insert(HsEntityIndex).values(
                        hs_code=code,
                        entity_type=etype,
                        entity_value=v.lower(),
                        weight=_label_weight(etype),
                    )
                    stmt2 = stmt2.on_conflict_do_update(
                        index_elements=["hs_code", "entity_type", "entity_value"],
                        set_={"weight": stmt2.excluded.weight},
                    )
                    await db.execute(stmt2)
                    upserted += 1
            if (idx + 1) % 200 == 0:
                await mark_progress(db, run, upserted)
                log.info("hs_entities.progress", processed=idx + 1, total=len(rows), upserted=upserted)
        await db.commit()
        run.rows_upserted = upserted


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=int, default=None, help="filter HS level (2, 4, 6); default all")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.level, args.limit))


if __name__ == "__main__":
    main()
