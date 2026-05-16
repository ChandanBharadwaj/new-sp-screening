from __future__ import annotations

import os
import time

import numpy as np

from app.config import settings

FEATURE_ORDER = [
    "dense_similarity",
    "sparse_score",
    "entity_overlap_score",
    "cross_encoder_score",
    "chapter_prior",
    "candidate_depth",
    "top1_minus_top2_gap",
]


class LtrRanker:
    """LightGBM lambdarank model loaded from a serialized text booster.

    If no model file exists yet, falls back to a deterministic linear blend
    so the pipeline still runs end-to-end before the LTR has been trained.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.ltr_model_path
        self.booster = None
        self.load_time_ms: int | None = None
        self.feature_order = FEATURE_ORDER
        if os.path.exists(self.path):
            import lightgbm as lgb

            t0 = time.perf_counter()
            self.booster = lgb.Booster(model_file=self.path)
            self.load_time_ms = int((time.perf_counter() - t0) * 1000)

    def predict(self, features: list[dict[str, float]]) -> list[float]:
        if not features:
            return []
        x = np.array(
            [[row.get(f, 0.0) or 0.0 for f in self.feature_order] for row in features],
            dtype=np.float32,
        )
        if self.booster is None:
            # Heuristic blend until a real model is trained.
            weights = np.array([0.20, 0.10, 0.15, 0.45, 0.05, 0.0, 0.05], dtype=np.float32)
            return [float(s) for s in (x @ weights)]
        return [float(s) for s in self.booster.predict(x)]
