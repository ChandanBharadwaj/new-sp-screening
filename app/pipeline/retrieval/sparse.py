from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

CODE_QUERY = text(
    """
    SELECT code, level, chapter, title, description,
           ts_rank_cd(description_tsv, plainto_tsquery('english', :q)) AS rank
    FROM hs_code
    WHERE description_tsv @@ plainto_tsquery('english', :q)
    ORDER BY rank DESC
    LIMIT :k
    """
)

TRAINING_QUERY = text(
    """
    SELECT hs_code, description,
           ts_rank_cd(description_tsv, plainto_tsquery('english', :q)) AS rank
    FROM hs_training_example
    WHERE description_tsv @@ plainto_tsquery('english', :q) AND hs_code IS NOT NULL
    ORDER BY rank DESC
    LIMIT :k
    """
)


async def search(db: AsyncSession, query_text: str) -> list[dict]:
    if not query_text.strip():
        return []
    code_rows = (await db.execute(CODE_QUERY, {"q": query_text, "k": settings.retrieval_top_k})).mappings().all()
    train_rows = (await db.execute(TRAINING_QUERY, {"q": query_text, "k": settings.retrieval_top_k})).mappings().all()

    # Normalize ts_rank scores roughly into [0, 1] using max over the result set.
    all_scores = [float(r["rank"]) for r in code_rows] + [float(r["rank"]) for r in train_rows]
    max_s = max(all_scores) if all_scores else 1.0
    if max_s <= 0:
        max_s = 1.0

    by_code: dict[str, dict] = {}
    for r in code_rows:
        c = r["code"]
        by_code[c] = {
            "hs_code": c,
            "level": r["level"],
            "chapter": r["chapter"],
            "title": r["title"],
            "description": r["description"],
            "sparse_score": float(r["rank"]) / max_s,
        }
    for r in train_rows:
        c = r["hs_code"]
        score = float(r["rank"]) / max_s
        if c in by_code:
            by_code[c]["sparse_score"] = max(by_code[c]["sparse_score"], score * 0.9)
        else:
            by_code[c] = {
                "hs_code": c,
                "level": None,
                "chapter": c[:2] if c else None,
                "title": None,
                "description": r["description"],
                "sparse_score": score * 0.9,
            }

    return list(by_code.values())
