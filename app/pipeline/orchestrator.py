from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.registry import ModelRegistry
from app.pipeline import assemble, confidence, fusion, ner, normalize, rerank, rules, sanctions
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
    shipment_value: float | None = None,
    currency: str | None = None,
    metadata: dict[str, Any] | None = None,
    shipment_id: UUID | None = None,
) -> dict[str, Any]:
    timer = StageTimer()
    sid = shipment_id or uuid4()

    raw_text = commodity_text + (" " + cargo_text if cargo_text else "")
    norm = normalize.normalize(raw_text)

    entities = await asyncio.to_thread(ner.extract, models.ner, norm)
    timer.mark("ner")

    # Stage 2 — hybrid retrieval (HS branch)
    dense_t = asyncio.create_task(dense.search(db, models.embedder, norm))
    sparse_t = asyncio.create_task(sparse.search(db, norm))
    entity_t = asyncio.create_task(entity.search(db, entities))
    dense_res, sparse_res, entity_res = await asyncio.gather(dense_t, sparse_t, entity_t)
    candidates = union.merge(dense_res, sparse_res, entity_res)
    timer.mark("retrieval")

    # Stage 3 — cross-encoder rerank
    candidates = await asyncio.to_thread(rerank.rerank, models.reranker, norm, candidates)
    timer.mark("rerank_hs")

    # Stage 4 — LightGBM fusion
    candidates = fusion.fuse(
        models.ltr, candidates, shipment={"origin": origin_iso, "destination": destination_iso}
    )
    timer.mark("fusion")

    # Stage 5 — sanctions + rules in parallel, off the top HS candidates
    top_hs_codes = [c.get("hs_code") for c in candidates[:20] if c.get("hs_code")]
    shipment_ctx = {
        "shipment_value": shipment_value,
        "currency": currency,
        "metadata": metadata,
    }
    sanctions_t = asyncio.create_task(
        sanctions.score(
            db=db,
            embedder=models.embedder,
            reranker=models.reranker,
            query_text=norm,
            candidate_hs_codes=top_hs_codes,
            origin_iso=origin_iso,
            destination_iso=destination_iso,
        )
    )
    rules_t = asyncio.create_task(
        rules.score(
            db=db,
            reranker=models.reranker,
            cargo_text=norm,
            origin_iso=origin_iso,
            destination_iso=destination_iso,
            shipment=shipment_ctx,
        )
    )
    sanction_matches, rule_matches = await asyncio.gather(sanctions_t, rules_t)
    timer.mark("sanctions_rules")

    # Stage 6 — confidence + assemble
    conf = confidence.compute(candidates)
    payload = assemble.build(sid, candidates, entities, conf, timer.snapshot())
    payload["sanction_matches"] = sanction_matches
    payload["rule_matches"] = rule_matches
    timer.mark("assemble")
    payload["latency_ms"] = timer.snapshot()

    log.info(
        "screen.done",
        shipment_id=str(sid),
        top1=payload["hs_classification"]["top_candidates"][0]["hs_code"]
        if payload["hs_classification"]["top_candidates"]
        else None,
        latency_ms=payload["latency_ms"]["total"],
        n_candidates=len(candidates),
        n_sanctions=len(sanction_matches),
        n_rules=len(rule_matches),
    )
    return payload
