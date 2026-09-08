"""The correct walk-forward twin: every transform lives inside a Pipeline, so
each fold fits only on its own training half, and the splitter is deterministic
by construction - asking it for a random_state would be the mistake.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

LAGS = (1, 2, 3, 24, 168)
TARGET = "demand"
N_SPLITS = 5


def build_frame(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path).sort_values("timestamp")
    for lag in LAGS:
        frame["lag_%d" % lag] = frame[TARGET].shift(lag)
    frame["rolling_24"] = frame[TARGET].shift(1).rolling(24).mean()
    return frame.dropna()


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", HistGradientBoostingRegressor(max_iter=300, random_state=0)),
    ])


def walk_forward(csv_path: str = "data/demand.csv"):
    frame = build_frame(csv_path)
    columns = ["lag_%d" % lag for lag in LAGS] + ["rolling_24"]
    features = frame[columns].to_numpy()
    target = frame[TARGET].to_numpy()

    scores = cross_val_score(build_pipeline(), features, target,
                             cv=TimeSeriesSplit(n_splits=N_SPLITS),
                             scoring="neg_mean_absolute_error")
    return float(np.mean(scores))


if __name__ == "__main__":
    print(walk_forward())
