"""Parity gate for an embedder generation swap (item 1).

Before cutting `sanctioned_commodity` over to `embedding_v2`, prove the new
generation does not regress retrieval. For a sample of held-out shipment
descriptions we retrieve top-50 from the sanctions dense path under each column,
rerank both with the *same* cross-encoder, and compare:

- Jaccard@10 of the two top-10 sets (agreement),
- recall@50 of v2 against the v1 result set used as the reference safety floor
  (or against an optional adjudicated gold set of relevant commodity ids),
- NDCG@10 of each ranking vs that reference.

Cutover criteria (sanctions safety floor — never regress recall):
  v2 recall@50 >= v1 recall@50 AND Jaccard@10 >= --min-jaccard AND 100% current
  rows have embedding_v2. Emits a JSON report with pass/fail.

USAGE:
    python -m eval.runners.embedding_parity \
        --queries eval/gold/parity_queries.txt \
        --target-model BAAI/bge-small-en-v1.6 \
        --report artifacts/embedding_parity.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.embedder import Embedder
from app.models.reranker import Reranker
from app.pipeline.sanctions import _dense_query, _vec_literal


async def _retrieve(db, embedder: Embedder, reranker: Reranker, column: str, query: str, k: int) -> list[int]:
    """Return reranked commodity ids (best first) from the dense path on `column`."""
    vec = embedder.encode_query(query)
    rows = (
        await db.execute(
            _dense_query(column),
            {"q": _vec_literal(vec), "origin": None, "destination": None, "k": k},
        )
    ).mappings().all()
    if not rows:
        return []
    scores = reranker.score_pairs(query, [r["description"] for r in rows])
    order = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
    return [int(rows[i]["id"]) for i in order]


def _jaccard(a: list[int], b: list[int], k: int) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0


def _recall_at(result: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 1.0
    return len(set(result[:k]) & relevant) / len(relevant)


def _ndcg_at(result: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 1.0
    dcg = sum(1.0 / math.log2(i + 2) for i, cid in enumerate(result[:k]) if cid in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


async def run_parity(
    queries: list[str],
    target_model: str,
    *,
    k: int = 50,
    min_jaccard: float = 0.6,
    gold: dict[str, list[int]] | None = None,
) -> dict:
    reranker = Reranker()
    v1_embedder = Embedder()  # active/settings model → 'embedding' column
    v2_embedder = Embedder(model_name=target_model)
    per_query = []
    jacc_sum = v1_recall_sum = v2_recall_sum = v1_ndcg_sum = v2_ndcg_sum = 0.0

    async with SessionLocal() as db:
        missing = (
            await db.execute(
                text(
                    "SELECT count(*) FROM sanctioned_commodity WHERE embedding_v2 IS NULL AND sys_to IS NULL"
                )
            )
        ).scalar_one()
        for q in queries:
            v1 = await _retrieve(db, v1_embedder, reranker, "embedding", q, k)
            v2 = await _retrieve(db, v2_embedder, reranker, "embedding_v2", q, k)
            # Reference relevant set: adjudicated gold if provided, else v1 top-10 as
            # the safety floor (v2 must preserve what v1 surfaced).
            relevant = set(gold.get(q, [])) if gold else set(v1[:10])
            jacc = _jaccard(v1, v2, 10)
            v1_recall, v2_recall = _recall_at(v1, relevant, k), _recall_at(v2, relevant, k)
            v1_ndcg, v2_ndcg = _ndcg_at(v1, relevant, 10), _ndcg_at(v2, relevant, 10)
            jacc_sum += jacc
            v1_recall_sum += v1_recall
            v2_recall_sum += v2_recall
            v1_ndcg_sum += v1_ndcg
            v2_ndcg_sum += v2_ndcg
            per_query.append(
                {"query": q, "jaccard@10": round(jacc, 4),
                 "v1_recall@50": round(v1_recall, 4), "v2_recall@50": round(v2_recall, 4),
                 "v1_ndcg@10": round(v1_ndcg, 4), "v2_ndcg@10": round(v2_ndcg, 4)}
            )

    n = max(len(queries), 1)
    mean_jacc = jacc_sum / n
    mean_v1_recall, mean_v2_recall = v1_recall_sum / n, v2_recall_sum / n
    passed = bool(missing == 0 and mean_v2_recall >= mean_v1_recall and mean_jacc >= min_jaccard)
    return {
        "target_model": target_model,
        "n_queries": len(queries),
        "rows_missing_v2": int(missing),
        "mean_jaccard@10": round(mean_jacc, 4),
        "mean_v1_recall@50": round(mean_v1_recall, 4),
        "mean_v2_recall@50": round(mean_v2_recall, 4),
        "mean_v1_ndcg@10": round(v1_ndcg_sum / n, 4),
        "mean_v2_ndcg@10": round(v2_ndcg_sum / n, 4),
        "min_jaccard_required": min_jaccard,
        "passed": passed,
        "per_query": per_query,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--queries", type=Path, required=True, help="newline-separated query texts")
    p.add_argument("--target-model", required=True)
    p.add_argument("--k", type=int, default=50)
    p.add_argument("--min-jaccard", type=float, default=0.6)
    p.add_argument("--gold", type=Path, default=None, help="optional JSON {query: [commodity_id,...]}")
    p.add_argument("--report", type=Path, default=Path("artifacts/embedding_parity.json"))
    args = p.parse_args()

    queries = [ln.strip() for ln in args.queries.read_text().splitlines() if ln.strip()]
    gold = json.loads(args.gold.read_text()) if args.gold else None
    result = asyncio.run(run_parity(queries, args.target_model, k=args.k, min_jaccard=args.min_jaccard, gold=gold))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "per_query"}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
