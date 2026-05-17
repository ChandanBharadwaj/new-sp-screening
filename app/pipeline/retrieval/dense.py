from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.embedder import Embedder

# Note: pgvector cosine distance operator is `<=>`. Lower is better; similarity = 1 - distance.

HS_CODE_QUERY = text(
    """
    SELECT code, level, chapter, title, description,
           1.0 - (embedding <=> CAST(:q AS vector)) AS similarity
    FROM hs_code
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:q AS vector)
    LIMIT :k
    """
)

TRAINING_QUERY = text(
    """
    SELECT hs_code, description,
           1.0 - (embedding <=> CAST(:q AS vector)) AS similarity
    FROM hs_training_example
    WHERE embedding IS NOT NULL AND hs_code IS NOT NULL
    ORDER BY embedding <=> CAST(:q AS vector)
    LIMIT :k
    """
)


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


async def search(db: AsyncSession, embedder: Embedder, query_text: str) -> list[dict]:
    # BGE asymmetric query prefix — see Embedder.encode_query / app/models/embedder.py.
    vec = await asyncio.to_thread(embedder.encode_query, query_text)
    qlit = _vec_literal(vec)

    # SET LOCAL hnsw.ef_search trades a fixed amount of CPU for higher recall;
    # only applies inside this transaction so other queries are unaffected.
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(settings.hnsw_ef_search)}"))

    code_rows = (await db.execute(HS_CODE_QUERY, {"q": qlit, "k": settings.retrieval_top_k})).mappings().all()
    train_rows = (await db.execute(TRAINING_QUERY, {"q": qlit, "k": settings.retrieval_top_k})).mappings().all()

    by_code: dict[str, dict] = {}
    for r in code_rows:
        c = r["code"]
        by_code[c] = {
            "hs_code": c,
            "level": r["level"],
            "chapter": r["chapter"],
            "title": r["title"],
            "description": r["description"],
            "dense_similarity": float(r["similarity"]),
            "dense_via_training": 0.0,
        }
    for r in train_rows:
        c = r["hs_code"]
        sim = float(r["similarity"])
        if c in by_code:
            by_code[c]["dense_via_training"] = max(by_code[c]["dense_via_training"], sim)
        else:
            by_code[c] = {
                "hs_code": c,
                "level": None,
                "chapter": c[:2] if c else None,
                "title": None,
                "description": r["description"],
                "dense_similarity": sim * 0.95,
                "dense_via_training": sim,
            }

    return list(by_code.values())
