"""Build a LightGBM-Ranking training set from the gold split.

For each gold (description, hs_code) pair we run hybrid retrieval (no rerank yet — we
add the cross-encoder score afterwards because it dominates cost), collect feature
vectors per candidate, and label relevance against the gold code:
    4 — exact subheading match
    3 — same heading (4-digit prefix)
    2 — same chapter (2-digit prefix)
    1 — adjacent chapter family (chapter ±1)
    0 — otherwise

Output: parquet/CSV at artifacts/ltr_train.csv with one row per (query, candidate).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.registry import load_models
from app.pipeline import normalize, rerank
from app.pipeline.retrieval import dense, entity, sparse, union
from app.telemetry import configure_logging, log


def _grade(gold: str, candidate: str) -> int:
    if not gold or not candidate:
        return 0
    if candidate == gold:
        return 4
    if candidate[:4] == gold[:4]:
        return 3
    if candidate[:2] == gold[:2]:
        return 2
    try:
        if abs(int(candidate[:2]) - int(gold[:2])) == 1:
            return 1
    except ValueError:
        pass
    return 0


async def _features_for_query(db: AsyncSession, models, qtext: str) -> list[dict]:
    norm = normalize.normalize(qtext)
    entities = models.ner.predict(norm)
    dense_t = dense.search(db, models.embedder, norm)
    sparse_t = sparse.search(db, norm)
    entity_t = entity.search(db, entities)
    dense_res, sparse_res, entity_res = await asyncio.gather(dense_t, sparse_t, entity_t)
    cands = union.merge(dense_res, sparse_res, entity_res)
    cands = rerank.rerank(models.reranker, norm, cands)
    return cands


async def main_async(gold_path: Path, out_path: Path, limit: int | None) -> None:
    configure_logging()
    models = load_models()
    rows: list[dict] = []
    qid = 0
    async with SessionLocal() as db:
        with gold_path.open() as f:
            lines = f.readlines()
            if limit:
                lines = lines[:limit]
            for line in lines:
                rec = json.loads(line)
                gold_code = rec["hs_code"]
                cands = await _features_for_query(db, models, rec["description"])
                for c in cands:
                    rows.append(
                        {
                            "qid": qid,
                            "label": _grade(gold_code, c.get("hs_code", "")),
                            "dense_similarity": max(c.get("dense_similarity", 0.0), c.get("dense_via_training", 0.0)),
                            "sparse_score": c.get("sparse_score", 0.0),
                            "entity_overlap_score": c.get("entity_overlap_score", 0.0),
                            "cross_encoder_score": c.get("cross_encoder_score", 0.0),
                            "chapter_prior": 0.0,  # filled at fusion time; stays 0 in training
                            "candidate_depth": float(c.get("level") or 6),
                            "top1_minus_top2_gap": 0.0,
                            "hs_code": c.get("hs_code"),
                            "gold_hs_code": gold_code,
                        }
                    )
                qid += 1
                if qid % 50 == 0:
                    log.info("ltr_dataset.progress", q=qid, rows=len(rows))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)
    log.info("ltr_dataset.done", out=str(out_path), n_queries=qid, n_rows=len(rows))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--gold", type=Path, default=Path("eval/gold/splits/train.jsonl"))
    p.add_argument("--out", type=Path, default=Path("artifacts/ltr_train.csv"))
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.gold, args.out, args.limit))


if __name__ == "__main__":
    main()
