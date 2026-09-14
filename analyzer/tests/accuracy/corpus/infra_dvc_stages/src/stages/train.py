"""DVC stage 2 — fit the demand model. **Both planted defects live here.**

1. line 52 — `train_test_split(..., shuffle=True)` on a table that is indexed by
   `reading_ts`, built from lags of its own target and sorted chronologically in
   stage 1. A random split puts hour 5000 in train and hour 4999 in test, and
   because every feature is a lag of the target the model can interpolate the
   holdout from its neighbours. The honest cut is the last 20% of the index
   (MLV106).
2. line 52 — and the split passes no `random_state=`, so two `dvc repro` runs of
   the same stage produce different holdouts and the metrics file is not
   comparable with itself (MLV602).

The estimator itself is fine: one `HistGradientBoostingRegressor`, fitted once,
on the training partition only, with its `random_state` taken from
`params.yaml`. Nothing is fitted before the split.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split

from .prepare import load_params


def build_estimator(settings, seed: int):
    if settings["estimator"] != "hist_gradient_boosting":
        raise ValueError("unknown estimator %r" % settings["estimator"])
    return HistGradientBoostingRegressor(
        max_iter=settings["max_iter"],
        learning_rate=settings["learning_rate"],
        max_leaf_nodes=settings["max_leaf_nodes"],
        l2_regularization=settings["l2_regularization"],
        random_state=seed,
    )


def main() -> None:
    params = load_params()
    base = params["base"]
    split_settings = params["split"]
    train_settings = params["train"]

    frame = pd.read_parquet(base["interim_path"])
    target = params["prepare"]["target_column"]
    features = frame.drop(columns=[target])
    labels = frame[target]

    x_train, x_hold, y_train, y_hold = train_test_split(
        features, labels, test_size=split_settings["test_size"], shuffle=True)

    model = build_estimator(train_settings, base["seed"])
    model.fit(x_train, y_train)

    Path(base["model_path"]).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, base["model_path"])

    holdout = x_hold.copy()
    holdout[target] = y_hold
    holdout.to_parquet("data/interim/holdout.parquet")
    print("trained on %d rows, held out %d" % (len(x_train), len(x_hold)))


if __name__ == "__main__":
    main()
