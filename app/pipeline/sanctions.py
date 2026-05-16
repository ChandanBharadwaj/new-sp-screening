"""Sanctions scoring stage — runs in parallel with HS rerank.

Two paths feed the final ranked match list:
1. STRUCTURED: top-K HS candidates from the HS branch are joined against country_rule
   for the shipment's (origin, destination); matches surface even with low semantic
   similarity because the rule is explicit.
2. SEMANTIC: dense + sparse retrieval over sanctioned_commodity (filtered to records
   whose country_rule scope is compatible with the shipment route), then a small
   cross-encoder rerank.

Returns a list shaped per README §10's sanction_matches.
"""
from __future__ import annotations

import asyncio
import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedder import Embedder
from app.models.reranker import Reranker

STRUCTURED_QUERY = text(
    """
    SELECT
        sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
        sc.restriction_type, sc.provenance_url,
        cr.origin_iso, cr.destination_iso, cr.conditions
    FROM sanctioned_commodity sc
    JOIN country_rule cr ON cr.sanctioned_commodity_id = sc.id
    WHERE cr.active = true
      AND (cr.origin_iso IS NULL OR cr.origin_iso = :origin)
      AND (cr.destination_iso IS NULL OR cr.destination_iso = :destination)
      AND sc.hs_codes && CAST(:codes AS varchar[])
    LIMIT :k
    """
)

DENSE_QUERY = text(
    """
    SELECT sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
           sc.restriction_type, sc.provenance_url,
           1.0 - (sc.embedding <=> CAST(:q AS vector)) AS similarity
    FROM sanctioned_commodity sc
    WHERE sc.embedding IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM country_rule cr
        WHERE cr.sanctioned_commodity_id = sc.id
          AND cr.active = true
          AND (cr.origin_iso IS NULL OR cr.origin_iso = :origin)
          AND (cr.destination_iso IS NULL OR cr.destination_iso = :destination)
      )
    ORDER BY sc.embedding <=> CAST(:q AS vector)
    LIMIT :k
    """
)

SPARSE_QUERY = text(
    """
    SELECT sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
           sc.restriction_type, sc.provenance_url,
           ts_rank_cd(sc.description_tsv, plainto_tsquery('english', :q)) AS rank
    FROM sanctioned_commodity sc
    WHERE sc.description_tsv @@ plainto_tsquery('english', :q)
      AND EXISTS (
        SELECT 1 FROM country_rule cr
        WHERE cr.sanctioned_commodity_id = sc.id
          AND cr.active = true
          AND (cr.origin_iso IS NULL OR cr.origin_iso = :origin)
          AND (cr.destination_iso IS NULL OR cr.destination_iso = :destination)
      )
    ORDER BY rank DESC
    LIMIT :k
    """
)


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


async def score(
    *,
    db: AsyncSession,
    embedder: Embedder,
    reranker: Reranker,
    query_text: str,
    candidate_hs_codes: list[str],
    origin_iso: str | None,
    destination_iso: str | None,
    top_k: int = 50,
    rerank_top: int = 10,
) -> list[dict]:
    # If neither side of the route is set, only run semantic; otherwise also run structured.
    structured_task = None
    if candidate_hs_codes:
        structured_task = db.execute(
            STRUCTURED_QUERY,
            {
                "origin": origin_iso,
                "destination": destination_iso,
                "codes": candidate_hs_codes,
                "k": top_k,
            },
        )

    vec = await asyncio.to_thread(embedder.encode_one, query_text)
    qlit = _vec_literal(vec)
    dense_task = db.execute(
        DENSE_QUERY, {"q": qlit, "origin": origin_iso, "destination": destination_iso, "k": top_k}
    )
    sparse_task = db.execute(
        SPARSE_QUERY,
        {"q": query_text, "origin": origin_iso, "destination": destination_iso, "k": top_k},
    )

    if structured_task is not None:
        structured_res, dense_res, sparse_res = await asyncio.gather(
            structured_task, dense_task, sparse_task
        )
    else:
        dense_res, sparse_res = await asyncio.gather(dense_task, sparse_task)
        structured_res = None

    by_id: dict[int, dict] = {}

    if structured_res is not None:
        for r in structured_res.mappings():
            by_id[int(r["id"])] = {
                "id": int(r["id"]),
                "source": r["source"],
                "source_record_id": r["source_record_id"],
                "description": r["description"],
                "hs_codes": list(r["hs_codes"] or []),
                "restriction_type": r["restriction_type"],
                "provenance_url": r["provenance_url"],
                "country_pair_applicable": True,
                "structured_match": True,
                "dense": 0.0,
                "sparse": 0.0,
            }

    dense_max = 0.0
    for r in dense_res.mappings():
        sim = float(r["similarity"])
        dense_max = max(dense_max, sim)
        rid = int(r["id"])
        existing = by_id.get(rid)
        if existing:
            existing["dense"] = max(existing["dense"], sim)
        else:
            by_id[rid] = {
                "id": rid,
                "source": r["source"],
                "source_record_id": r["source_record_id"],
                "description": r["description"],
                "hs_codes": list(r["hs_codes"] or []),
                "restriction_type": r["restriction_type"],
                "provenance_url": r["provenance_url"],
                "country_pair_applicable": True,
                "structured_match": False,
                "dense": sim,
                "sparse": 0.0,
            }

    sparse_max = 0.0
    for r in sparse_res.mappings():
        rank = float(r["rank"])
        sparse_max = max(sparse_max, rank)
        rid = int(r["id"])
        existing = by_id.get(rid)
        if existing:
            existing["sparse"] = max(existing["sparse"], rank)
        else:
            by_id[rid] = {
                "id": rid,
                "source": r["source"],
                "source_record_id": r["source_record_id"],
                "description": r["description"],
                "hs_codes": list(r["hs_codes"] or []),
                "restriction_type": r["restriction_type"],
                "provenance_url": r["provenance_url"],
                "country_pair_applicable": True,
                "structured_match": False,
                "dense": 0.0,
                "sparse": rank,
            }

    if not by_id:
        return []

    # Normalize sparse scores; cross-encoder rerank top-N by a blended pre-score.
    def pre_score(c: dict) -> float:
        norm_sparse = (c["sparse"] / sparse_max) if sparse_max > 0 else 0.0
        bonus = 0.3 if c["structured_match"] else 0.0
        return max(c["dense"], norm_sparse) + bonus

    ordered = sorted(by_id.values(), key=pre_score, reverse=True)
    head = ordered[:rerank_top]
    texts = [c["description"] for c in head]
    cross_scores = await asyncio.to_thread(reranker.score_pairs, query_text, texts)
    cross_norm = [_sigmoid(s) for s in cross_scores]
    for c, s in zip(head, cross_norm, strict=True):
        c["cross_encoder"] = float(s)
    for c in ordered[rerank_top:]:
        c["cross_encoder"] = 0.0

    out: list[dict] = []
    for c in ordered:
        hs_overlap = sorted(set(c["hs_codes"]) & set(candidate_hs_codes))
        norm_sparse = (c["sparse"] / sparse_max) if sparse_max > 0 else 0.0
        similarity = max(c["dense"], c["cross_encoder"])
        out.append(
            {
                "source": c["source"],
                "source_record_id": c["source_record_id"],
                "description": c["description"],
                "similarity": round(similarity, 4),
                "country_pair_applicable": c["country_pair_applicable"],
                "hs_code_overlap": hs_overlap,
                "restriction_type": c["restriction_type"],
                "provenance_url": c["provenance_url"],
                "score_components": {
                    "dense": round(c["dense"], 4),
                    "sparse": round(norm_sparse, 4),
                    "cross_encoder": round(c["cross_encoder"], 4),
                    "structured_match": c["structured_match"],
                },
            }
        )
    return out
