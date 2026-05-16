"""Train a LightGBM lambdarank model from artifacts/ltr_train.csv.

USAGE:
    python -m app.training.ltr_train --in artifacts/ltr_train.csv --out artifacts/ltr.txt
"""
from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import pandas as pd

from app.models.ltr import FEATURE_ORDER
from app.telemetry import configure_logging, log


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", type=Path, default=Path("artifacts/ltr_train.csv"))
    p.add_argument("--out", type=Path, default=Path("artifacts/ltr.txt"))
    args = p.parse_args()

    df = pd.read_csv(args.in_path)
    log.info("ltr_train.loaded", n_rows=len(df), n_queries=df["qid"].nunique())

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
        "verbose": -1,
    }
    booster = lgb.train(params, train_set, num_boost_round=300)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(args.out))
    log.info("ltr_train.saved", out=str(args.out))


if __name__ == "__main__":
    main()
