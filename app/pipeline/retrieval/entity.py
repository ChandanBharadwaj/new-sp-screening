from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

QUERY = text(
    """
    SELECT hs.code, hs.level, hs.chapter, hs.title, SUM(hei.weight) AS score
    FROM hs_entity_index hei
    JOIN hs_code hs ON hs.code = hei.hs_code
    WHERE (hei.entity_type, hei.entity_value) = ANY(CAST(:pairs AS text[][]))
    GROUP BY hs.code, hs.level, hs.chapter, hs.title
    ORDER BY score DESC
    LIMIT :k
    """
)


def _flatten(entities: dict[str, list[str]]) -> list[tuple[str, str]]:
    out = []
    for etype, values in entities.items():
        for v in values:
            if v:
                out.append((etype, v.lower()))
    return out


async def search(db: AsyncSession, entities: dict[str, list[str]]) -> list[dict]:
    pairs = _flatten(entities)
    if not pairs:
        return []
    # Build a Postgres text[][] literal: '{{material,cotton},{form,woven}}'
    def esc(v: str) -> str:
        v = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{v}"'

    inner = ",".join("{" + f"{esc(t)},{esc(v)}" + "}" for t, v in pairs)
    array_lit = "{" + inner + "}"
    rows = (await db.execute(QUERY, {"pairs": array_lit, "k": settings.retrieval_top_k})).mappings().all()
    if not rows:
        return []
    max_s = max(float(r["score"]) for r in rows) or 1.0
    return [
        {
            "hs_code": r["code"],
            "level": r["level"],
            "chapter": r["chapter"],
            "title": r["title"],
            "entity_overlap_score": float(r["score"]) / max_s,
        }
        for r in rows
    ]
