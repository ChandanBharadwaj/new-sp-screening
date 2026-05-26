"""Sanctions scoring stage — runs in parallel with HS rerank.

Two paths feed the final ranked match list:
1. STRUCTURED: top-K HS candidates from the HS branch are joined against country_rule
   for the shipment's (origin, destination); matches surface even with low semantic
   similarity because the rule is explicit.
2. SEMANTIC: dense + sparse retrieval over sanctioned_commodity (filtered to records
   whose country_rule scope is compatible with the shipment route), then a small
   cross-encoder rerank.

All four retrieval paths apply an effective-date predicate so expired sanction
records don't surface. Path-level results are blended with Reciprocal Rank Fusion
when ``settings.fusion_mode == "rrf"`` (default); ``"max"`` reproduces the legacy
score-blend as a rollback.

Returns a list shaped per README §10's sanction_matches.
"""
from __future__ import annotations

import asyncio
import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.embedder import Embedder
from app.models.reranker import Reranker
from app.pipeline.normalize_party import is_short_name, normalize_party

# Apply this predicate to every retrieval path so an expired sanction (eg. a
# heading whose effective_to has passed) doesn't surface. NULL endpoints mean
# "no bound" — only finite, in-the-past dates are filtered out.
_EFFECTIVE_DATE_CLAUSE = (
    "AND (sc.effective_from IS NULL OR sc.effective_from <= CURRENT_DATE) "
    "AND (sc.effective_to   IS NULL OR sc.effective_to   >= CURRENT_DATE)"
)

# Bitemporal hot path: screen only the current version of each commodity
# (migration 0009). Historical versions exist solely for point-in-time replay.
_CURRENT_VERSION_CLAUSE = "AND sc.sys_to IS NULL"

STRUCTURED_QUERY = text(
    f"""
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
      {_EFFECTIVE_DATE_CLAUSE}
      {_CURRENT_VERSION_CLAUSE}
    LIMIT :k
    """
)

DENSE_QUERY = text(
    f"""
    SELECT sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
           sc.restriction_type, sc.provenance_url,
           1.0 - (sc.embedding <=> CAST(:q AS vector)) AS similarity
    FROM sanctioned_commodity sc
    WHERE sc.embedding IS NOT NULL
      {_EFFECTIVE_DATE_CLAUSE}
      {_CURRENT_VERSION_CLAUSE}
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
    f"""
    SELECT sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
           sc.restriction_type, sc.provenance_url,
           ts_rank_cd(sc.description_tsv, plainto_tsquery('simple', :q)) AS rank
    FROM sanctioned_commodity sc
    WHERE sc.description_tsv @@ plainto_tsquery('simple', :q)
      {_EFFECTIVE_DATE_CLAUSE}
      {_CURRENT_VERSION_CLAUSE}
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

# Trigram-fuzzy alias match. Joins sanctioned_commodity_alias (populated by
# OFAC SDN's alt.csv plus UN/EU consolidated alias extraction) via the GIN trgm
# index, then back to the parent sanctioned_commodity. The
# ``similarity(...) >= :min_sim`` predicate is what makes the
# ``gin_trgm_ops`` index applicable; pg's planner will use it before the join.
ALIAS_QUERY = text(
    f"""
    SELECT sc.id, sc.source, sc.source_record_id, sc.description, sc.hs_codes,
           sc.restriction_type, sc.provenance_url,
           MAX(similarity(a.alias, :q)) AS sim
    FROM sanctioned_commodity_alias a
    JOIN sanctioned_commodity sc ON sc.id = a.sanctioned_commodity_id
    WHERE a.alias %% :q
      AND similarity(a.alias, :q) >= :min_sim
      {_EFFECTIVE_DATE_CLAUSE}
      {_CURRENT_VERSION_CLAUSE}
    GROUP BY sc.id
    ORDER BY sim DESC
    LIMIT :k
    """
)


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _rrf_blend(
    *,
    structured: list[dict] | None,
    dense: list[dict],
    sparse: list[dict],
    alias: list[dict] | None,
    by_id: dict[int, dict],
    sparse_max: float,
) -> None:
    """Mutate `by_id` records in-place, filling `rrf_score` from per-path ranks.

    ``settings.fusion_mode == "max"`` falls back to the legacy blend (kept here
    so a single switch in app/config.py rolls back the whole change).
    Structured matches contribute as a virtual rank-0 channel — they win ties
    against pure semantic signals, which is the same intent as the legacy
    ``+0.3`` structured bonus, but expressed in rank space so it composes
    naturally with the rest of the RRF sum.
    """
    if settings.fusion_mode != "rrf":
        for c in by_id.values():
            norm_sparse = (c["sparse"] / sparse_max) if sparse_max > 0 else 0.0
            bonus = 0.3 if c["structured_match"] else 0.0
            signal = max(c["dense"], norm_sparse, c["alias_sim"])
            c["rrf_score"] = signal + bonus
        return

    k = settings.rrf_k
    for c in by_id.values():
        c["rrf_score"] = 0.0
        if c["structured_match"]:
            # Virtual rank 0 — guarantees a structured match scores above any
            # candidate that only appears in the semantic paths.
            c["rrf_score"] += 1.0 / (k + 0 + 1)

    for source in (structured, dense, sparse, alias):
        if not source:
            continue
        for rank_idx, item in enumerate(source):
            rid = int(item["id"])
            target = by_id.get(rid)
            if target is None:
                continue
            target["rrf_score"] += 1.0 / (k + rank_idx + 1)


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
    rerank_top: int | None = None,
) -> list[dict]:
    if rerank_top is None:
        rerank_top = settings.sanctions_rerank_top_k

    # SET LOCAL only affects this transaction — safe to leave on by default.
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}"))

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

    # BGE asymmetric query prefix — documents stay unprefixed.
    vec = await asyncio.to_thread(embedder.encode_query, query_text)
    qlit = _vec_literal(vec)
    dense_task = db.execute(
        DENSE_QUERY, {"q": qlit, "origin": origin_iso, "destination": destination_iso, "k": top_k}
    )
    sparse_task = db.execute(
        SPARSE_QUERY,
        {"q": query_text, "origin": origin_iso, "destination": destination_iso, "k": top_k},
    )

    # Alias trigram path: normalize the query, then suppress for short / generic strings
    # ("Smith") that would firehose false positives.
    party_query = normalize_party(query_text)
    alias_task = None
    if party_query and not is_short_name(party_query):
        alias_task = db.execute(
            ALIAS_QUERY,
            {"q": party_query, "min_sim": 0.45, "k": top_k},
        )

    awaitables = [t for t in (structured_task, dense_task, sparse_task, alias_task) if t is not None]
    results = await asyncio.gather(*awaitables)
    # Map results back in declared order.
    idx = 0
    structured_res = None
    if structured_task is not None:
        structured_res = results[idx]
        idx += 1
    dense_res = results[idx]
    idx += 1
    sparse_res = results[idx]
    idx += 1
    alias_res = results[idx] if alias_task is not None else None

    by_id: dict[int, dict] = {}
    structured_rows: list[dict] = []
    dense_rows: list[dict] = []
    sparse_rows: list[dict] = []
    alias_rows: list[dict] = []

    if structured_res is not None:
        for r in structured_res.mappings():
            row = {
                "id": int(r["id"]),
                "source": r["source"],
                "source_record_id": r["source_record_id"],
                "description": r["description"],
                "hs_codes": list(r["hs_codes"] or []),
                "restriction_type": r["restriction_type"],
                "provenance_url": r["provenance_url"],
            }
            structured_rows.append(row)
            by_id[row["id"]] = {
                **row,
                "country_pair_applicable": True,
                "structured_match": True,
                "dense": 0.0,
                "sparse": 0.0,
                "alias_sim": 0.0,
            }

    dense_max = 0.0
    for r in dense_res.mappings():
        sim = float(r["similarity"])
        dense_max = max(dense_max, sim)
        rid = int(r["id"])
        dense_rows.append({"id": rid})
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
                "alias_sim": 0.0,
            }

    sparse_max = 0.0
    for r in sparse_res.mappings():
        rank = float(r["rank"])
        sparse_max = max(sparse_max, rank)
        rid = int(r["id"])
        sparse_rows.append({"id": rid})
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
                "alias_sim": 0.0,
            }

    if alias_res is not None:
        for r in alias_res.mappings():
            sim = float(r["sim"])
            rid = int(r["id"])
            alias_rows.append({"id": rid})
            existing = by_id.get(rid)
            if existing:
                existing["alias_sim"] = max(existing["alias_sim"], sim)
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
                    "sparse": 0.0,
                    "alias_sim": sim,
                }

    if not by_id:
        return []

    _rrf_blend(
        structured=structured_rows,
        dense=dense_rows,
        sparse=sparse_rows,
        alias=alias_rows,
        by_id=by_id,
        sparse_max=sparse_max,
    )

    ordered = sorted(by_id.values(), key=lambda c: c["rrf_score"], reverse=True)
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
        alias_sim = c["alias_sim"]
        # Surfaced similarity stays in the same shape downstream API consumers
        # expect (max over semantic signals); rrf_score is exposed alongside for
        # transparency in score_components.
        similarity = max(c["dense"], c["cross_encoder"], alias_sim)
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
                    "alias_trigram": round(alias_sim, 4),
                    "structured_match": c["structured_match"],
                    "rrf_score": round(c["rrf_score"], 6),
                },
            }
        )
    return out
