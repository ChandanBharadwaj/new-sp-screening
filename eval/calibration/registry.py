"""Registry of every calibratable threshold (item 3).

One declarative entry per tunable. The calibration pipeline iterates this list:
- `post_hoc` thresholds are swept in-memory over harvested per-query features
  (no pipeline re-run) — they only affect the abstention decision.
- `retrieval` thresholds change what the pipeline retrieves, so they are swept by
  re-running the pipeline with an injected policy override.
- `reported_only` tunables are structural ints living in app/config.py (env), not
  the policy tables; they are swept/reported but never auto-written.

`store` says where an applied value is written: ("inference_threshold", pipeline,
parameter) or ("policy_parameter", scope, name). `reported_only` entries have store=None.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Threshold:
    name: str
    kind: str  # 'post_hoc' | 'retrieval' | 'reported_only'
    current: float
    lo: float
    hi: float
    step: float
    # Where to write an applied value, or None for reported_only.
    store: tuple[str, str, str] | None
    # For post_hoc abstention thresholds: which harvested feature it gates and the
    # direction ('min' = accept when feature >= value).
    feature: str | None = None

    def sweep_values(self) -> list[float]:
        vals: list[float] = []
        v = self.lo
        # Inclusive of hi within float tolerance.
        while v <= self.hi + 1e-9:
            vals.append(round(v, 6))
            v += self.step
        return vals


REGISTRY: list[Threshold] = [
    # --- post_hoc: abstention thresholds (swept over harvested features) ---
    Threshold("min_top1", "post_hoc", 0.45, 0.30, 0.60, 0.01,
              ("inference_threshold", "hs_classify", "min_top1"), feature="top1_score"),
    Threshold("min_gap", "post_hoc", 0.05, 0.01, 0.15, 0.01,
              ("inference_threshold", "hs_classify", "min_gap"), feature="gap"),
    Threshold("min_chapter_consensus", "post_hoc", 0.40, 0.20, 0.60, 0.02,
              ("inference_threshold", "hs_classify", "min_chapter_consensus"), feature="chapter_consensus"),
    Threshold("cross_source_dense_floor", "post_hoc", 0.40, 0.20, 0.60, 0.02,
              ("policy_parameter", "confidence", "cross_source_dense_floor"), feature="dense"),
    Threshold("cross_source_ce_floor", "post_hoc", 0.40, 0.20, 0.60, 0.02,
              ("policy_parameter", "confidence", "cross_source_ce_floor"), feature="cross_encoder"),
    # --- retrieval: require pipeline re-run per grid point ---
    Threshold("gliner_min_score", "retrieval", 0.40, 0.30, 0.60, 0.05,
              ("policy_parameter", "gliner", "min_score")),
    Threshold("alias_min_similarity", "retrieval", 0.45, 0.30, 0.60, 0.05,
              ("policy_parameter", "alias_match", "min_similarity")),
    Threshold("decompose_conf_gate", "retrieval", 0.50, 0.30, 0.70, 0.05,
              ("policy_parameter", "decompose", "conf_gate")),
    # --- reported_only: structural ints in app/config.py (env), not policy tables ---
    Threshold("rerank_top_k", "reported_only", 20, 10, 50, 10, None),
    Threshold("hnsw_ef_search", "reported_only", 80, 40, 160, 20, None),
    Threshold("rrf_k", "reported_only", 60, 20, 100, 20, None),
]


def by_kind(kind: str) -> list[Threshold]:
    return [t for t in REGISTRY if t.kind == kind]
