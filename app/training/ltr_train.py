"""Train a LightGBM lambdarank model from artifacts/ltr_train.csv.

USAGE:
    python -m app.training.ltr_train --in artifacts/ltr_train.csv --out artifacts/ltr.txt
"""
from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import lightgbm as lgb
import pandas as pd

from app.models.ltr import FEATURE_ORDER
from app.telemetry import configure_logging, log

LogFn = Callable[[str], None]


def fit_booster(
    in_path: Path,
    out_path: Path,
    log_fn: LogFn | None = None,
) -> dict[str, Any]:
    """Reusable entrypoint — CLI and the arq worker both call this."""
    configure_logging()
    df = pd.read_csv(in_path)
    msg = f"Loaded {len(df)} rows / {df['qid'].nunique()} queries from {in_path}"
    log.info("ltr_train.loaded", n_rows=len(df), n_queries=df["qid"].nunique())
    if log_fn:
        log_fn(msg)

    df = df.sort_values("qid")
    group_sizes = df.groupby("qid").size().tolist()
    x = df[FEATURE_ORDER].astype("float32").values
    y = df["label"].astype(int).values

    train_set = lgb.Dataset(x, label=y, group=group_sizes)
    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [1, 3, 5],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 5,
        # Align the lambdarank gradient horizon with the cross-encoder hard cap
        # (rerank._CE_HARD_CAP) so optimisation matches what deployment actually
        # reranks (item 5).
        "lambdarank_truncation_level": 50,
        "verbose": -1,
    }
    if log_fn:
        log_fn("Training LightGBM lambdarank (300 rounds)…")
    t0 = time.perf_counter()
    booster = lgb.train(params, train_set, num_boost_round=300)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_path))
    log.info("ltr_train.saved", out=str(out_path))

    # Training-set NDCG so the UI has a metric to show.
    eval_result = booster.eval_train(feval=None)  # uses metric=ndcg from params
    ndcg = {name: float(score) for _, name, score, _ in eval_result}
    metrics = {
        "n_rows": int(len(df)),
        "n_queries": int(df["qid"].nunique()),
        "training_time_ms": elapsed_ms,
        "ndcg": ndcg,
    }
    if log_fn:
        log_fn(f"Saved booster → {out_path}; training_time_ms={elapsed_ms}; ndcg={ndcg}")
    return {"out_path": str(out_path), **metrics}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, default=Path("artifacts/ltr_train.csv"))
    p.add_argument("--out", type=Path, default=Path("artifacts/ltr.txt"))
    args = p.parse_args()
    fit_booster(args.in_path, args.out)


if __name__ == "__main__":
    main()
