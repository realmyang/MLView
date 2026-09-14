"""Walk-forward evaluation of an hourly load forecast, done correctly.

The holdout is a chronological cut, not a random one: the last 14 days are
sliced off by position after sorting, and `TimeSeriesSplit` supplies the inner
folds, so every training window ends before the fold it is scored on begins.
The scaler lives inside the `Pipeline`, so it is refit on each fold's own past.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from lags import TARGET, build, feature_columns

HOLDOUT_HOURS = 24 * 14
N_SPLITS = 5
SEED = 7


def make_estimator() -> Pipeline:
    return Pipeline(steps=[
        ("scale", StandardScaler()),
        ("gbm", HistGradientBoostingRegressor(max_iter=400, learning_rate=0.05,
                                              random_state=SEED)),
    ])


def chronological_cut(frame):
    columns = feature_columns(frame)
    cutoff = len(frame) - HOLDOUT_HOURS
    past = frame.iloc[:cutoff]
    future = frame.iloc[cutoff:]
    return (past[columns], past[TARGET], future[columns], future[TARGET])


def walk_forward(train_x, train_y) -> float:
    splitter = TimeSeriesSplit(n_splits=N_SPLITS, gap=24)
    scores = cross_val_score(make_estimator(), train_x, train_y, cv=splitter,
                             scoring="neg_mean_absolute_error")
    return float(-np.mean(scores))


def fit_and_score(train_x, train_y, test_x, test_y) -> float:
    estimator = make_estimator()
    estimator.fit(train_x, train_y)
    predictions = estimator.predict(test_x)
    return float(mean_absolute_error(test_y, predictions))


def main(csv_path: str = "data/load.csv") -> dict:
    frame = build(csv_path)
    train_x, train_y, test_x, test_y = chronological_cut(frame)
    return {
        "cv_mae": walk_forward(train_x, train_y),
        "holdout_mae": fit_and_score(train_x, train_y, test_x, test_y),
    }


if __name__ == "__main__":
    print(main())
