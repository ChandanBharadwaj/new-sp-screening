from typing import Any

NUMERIC_FIELDS = ("dense_similarity", "dense_via_training", "sparse_score", "entity_overlap_score")
META_FIELDS = ("level", "chapter", "title", "description")


def merge(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for src in sources:
        for cand in src:
            c = cand.get("hs_code")
            if not c:
                continue
            if c not in by_code:
                by_code[c] = {
                    "hs_code": c,
                    "level": None,
                    "chapter": c[:2] if c else None,
                    "title": None,
                    "description": None,
                    "dense_similarity": 0.0,
                    "dense_via_training": 0.0,
                    "sparse_score": 0.0,
                    "entity_overlap_score": 0.0,
                }
            existing = by_code[c]
            for f in NUMERIC_FIELDS:
                if f in cand:
                    existing[f] = max(existing[f], float(cand[f]))
            for f in META_FIELDS:
                if cand.get(f) and not existing.get(f):
                    existing[f] = cand[f]
    return list(by_code.values())
