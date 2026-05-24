from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.registry import ModelRegistry
from app.pipeline import (
    assemble,
    confidence,
    decompose,
    fusion,
    ner,
    normalize,
    rerank,
    rules,
    sanctions,
    versions,
)
from app.pipeline.retrieval import dense, entity, sparse, union
from app.telemetry import StageTimer, log

# Confidence floor below which we ignore a multi-commodity split and fall back to
# single-commodity. Tunable; see decompose.py.
_DECOMPOSE_CONF_GATE = 0.5


async def _hs_rank_for_text(
    *,
    db: AsyncSession,
    models: ModelRegistry,
    norm_text: str,
    origin_iso: str | None,
    destination_iso: str | None,
    entities: dict[str, list[str]],
) -> list[dict]:
    """Run dense+sparse+entity retrieval → cross-encoder rerank → LightGBM fusion
    for a single (normalized) commodity text. Returns the ranked candidate list."""
    dense_t = asyncio.create_task(dense.search(db, models.embedder, norm_text))
    sparse_t = asyncio.create_task(sparse.search(db, norm_text))
    entity_t = asyncio.create_task(entity.search(db, entities))
    dense_res, sparse_res, entity_res = await asyncio.gather(dense_t, sparse_t, entity_t)
    cands = union.merge(dense_res, sparse_res, entity_res)
    cands = await asyncio.to_thread(rerank.rerank, models.reranker, norm_text, cands)
    cands = fusion.fuse(
        models.ltr, cands, shipment={"origin": origin_iso, "destination": destination_iso}
    )
    return cands


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
    static_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timer = StageTimer()
    sid = shipment_id or uuid4()

    raw_text = commodity_text + (" " + cargo_text if cargo_text else "")
    norm = normalize.normalize(raw_text)

    # NER output is structured `{label: [{text, start, end, score}]}` for UI
    # highlighting; downstream retrieval/decomposition only needs the surface
    # forms, so we flatten right after the call.
    entities = await asyncio.to_thread(ner.extract, models.ner, norm)
    entities_flat = ner.flatten_to_text(entities)
    timer.mark("ner")

    # Stage 2 — primary HS ranking (single-commodity path).
    candidates = await _hs_rank_for_text(
        db=db,
        models=models,
        norm_text=norm,
        origin_iso=origin_iso,
        destination_iso=destination_iso,
        entities=entities_flat,
    )
    timer.mark("retrieval_rerank_fusion")

    # Stage 2b — multi-commodity decomposition. If the decomposer is confident the
    # text describes ≥2 distinct commodities, re-run HS ranking per sub-text and
    # surface a list of top-1 HS candidates. Single-commodity case is unaffected.
    decomp = decompose.split_into_commodities(norm, entities_flat)
    multi_top1: list[dict] | None = None
    if decomp.confidence >= _DECOMPOSE_CONF_GATE and len(decomp.fragments) >= 2:
        sub_results = []
        for frag in decomp.fragments:
            # Re-extract NER per fragment so entity overlap features remain local.
            sub_entities = await asyncio.to_thread(ner.extract, models.ner, frag.text)
            sub_cands = await _hs_rank_for_text(
                db=db,
                models=models,
                norm_text=frag.text,
                origin_iso=origin_iso,
                destination_iso=destination_iso,
                entities=ner.flatten_to_text(sub_entities),
            )
            if sub_cands:
                sub_results.append(sub_cands[0])
        if sub_results:
            multi_top1 = sub_results
        timer.mark("multi_commodity")

    # Stage 5 — sanctions + rules in parallel, off the top HS candidates.
    # If `candidates` is empty (HS retrieval found nothing) `top_hs_codes` is empty
    # too; sanctions.score then silently skips the structured-overlap path and falls
    # back to dense+sparse+alias matching, which is intentional. Documented here
    # because it's easy to miss when refactoring.
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

    # Stage 6 — confidence + abstention + version stamp + assemble.
    conf = confidence.compute(candidates)
    abst = confidence.compute_abstention(candidates, conf)
    fallback = (
        confidence.fallback_candidate(candidates, abst.get("fallback_level"))
        if abst.get("abstained")
        else None
    )
    # Version stamp: static parts (engine, model hashes) come from app.state if available;
    # refdata snapshot is queried per-request to capture latest successful ingest times.
    static = static_versions or versions.compute_static()
    vers = await versions.build(db, static)

    payload = assemble.build(
        sid,
        candidates,
        entities,
        conf,
        timer.snapshot(),
        abstention=abst,
        fallback=fallback,
        multi_commodity=multi_top1,
        versions=vers,
    )
    payload["sanction_matches"] = sanction_matches
    payload["rule_matches"] = rule_matches
    payload["rule_matches_by_list"] = assemble.group_rule_matches_by_list(rule_matches)
    timer.mark("assemble")
    payload["latency_ms"] = timer.snapshot()

    log.info(
        "screen.done",
        shipment_id=str(sid),
        top1=payload["hs_classification"]["top_candidates"][0]["hs_code"]
        if payload["hs_classification"]["top_candidates"]
        else None,
        abstained=payload["hs_classification"]["abstained"],
        multi_commodity_n=len(multi_top1) if multi_top1 else 0,
        latency_ms=payload["latency_ms"]["total"],
        n_candidates=len(candidates),
        n_sanctions=len(sanction_matches),
        n_rules=len(rule_matches),
    )
    return payload
