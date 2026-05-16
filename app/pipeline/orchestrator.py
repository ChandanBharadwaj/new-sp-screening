from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.registry import ModelRegistry
from app.pipeline import assemble, confidence, fusion, ner, normalize, rerank
from app.pipeline.retrieval import dense, entity, sparse, union
from app.telemetry import StageTimer, log


async def run_screen(
    *,
    db: AsyncSession,
    models: ModelRegistry,
    commodity_text: str,
    cargo_text: str | None = None,
    origin_iso: str | None = None,
    destination_iso: str | None = None,
    shipment_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timer = StageTimer()
    sid = shipment_id or uuid4()

    raw_text = commodity_text + (" " + cargo_text if cargo_text else "")
    norm = normalize.normalize(raw_text)

    entities = await asyncio.to_thread(ner.extract, models.ner, norm)
    timer.mark("ner")

    dense_t = asyncio.create_task(dense.search(db, models.embedder, norm))
    sparse_t = asyncio.create_task(sparse.search(db, norm))
    entity_t = asyncio.create_task(entity.search(db, entities))
    dense_res, sparse_res, entity_res = await asyncio.gather(dense_t, sparse_t, entity_t)
    candidates = union.merge(dense_res, sparse_res, entity_res)
    timer.mark("retrieval")

    candidates = await asyncio.to_thread(rerank.rerank, models.reranker, norm, candidates)
    timer.mark("rerank_hs")

    candidates = fusion.fuse(models.ltr, candidates, shipment={"origin": origin_iso, "destination": destination_iso})
    timer.mark("fusion")

    conf = confidence.compute(candidates)
    payload = assemble.build(sid, candidates, entities, conf, timer.snapshot())
    timer.mark("assemble")

    log.info(
        "screen.done",
        shipment_id=str(sid),
        top1=payload["hs_classification"]["top_candidates"][0]["hs_code"]
        if payload["hs_classification"]["top_candidates"]
        else None,
        latency_ms=payload["latency_ms"]["total"],
        n_candidates=len(candidates),
    )
    return payload
