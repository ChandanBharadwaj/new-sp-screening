"""Merge retrieval candidates from the dense / sparse / entity branches.

Two blending modes are supported via `settings.fusion_mode`:

- ``"rrf"`` (default) — Reciprocal Rank Fusion. Each input list contributes ranks
  by position, and per-candidate ``rrf_score = Σ 1 / (rrf_k + rank_i)``. Scale-
  invariant, so a sparse source whose ts_rank values live in [0, 0.05] and a
  dense source whose cosine similarities live in [0, 1] are weighted by *order*
  rather than absolute value. The standard k=60 follows Cormack et al. 2009.
- ``"max"`` — the legacy per-field ``max()`` blender. Kept as a no-restart
  rollback (``FUSION_MODE=max`` in env).

In both modes the existing per-source numeric fields (dense_similarity, etc.)
are preserved unchanged on the output dicts, so LightGBM LTR features in
``app/pipeline/fusion.py`` continue to work and ``rrf_score`` is additive.
"""
from __future__ import annotations

from typing import Any

from app.config import settings

NUMERIC_FIELDS = ("dense_similarity", "dense_via_training", "sparse_score", "entity_overlap_score")
META_FIELDS = ("level", "chapter", "title", "description")

_EMPTY_TEMPLATE: dict[str, Any] = {
    "level": None,
    "title": None,
    "description": None,
    "dense_similarity": 0.0,
    "dense_via_training": 0.0,
    "sparse_score": 0.0,
    "entity_overlap_score": 0.0,
}


def _ensure(by_code: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    existing = by_code.get(code)
    if existing is not None:
        return existing
    row = dict(_EMPTY_TEMPLATE)
    row["hs_code"] = code
    row["chapter"] = code[:2] if code else None
    row["rrf_score"] = 0.0
    by_code[code] = row
    return row


def merge(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    rrf_mode = settings.fusion_mode == "rrf"
    k = settings.rrf_k

    for src in sources:
        for rank_idx, cand in enumerate(src):
            c = cand.get("hs_code")
            if not c:
                continue
            existing = _ensure(by_code, c)
            for f in NUMERIC_FIELDS:
                if f in cand:
                    existing[f] = max(existing[f], float(cand[f]))
            for f in META_FIELDS:
                if cand.get(f) and not existing.get(f):
                    existing[f] = cand[f]
            if rrf_mode:
                existing["rrf_score"] += 1.0 / (k + rank_idx + 1)

    return list(by_code.values())
