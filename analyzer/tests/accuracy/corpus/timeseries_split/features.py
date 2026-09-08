"""Lag features for an hourly demand forecast.

Planted defects: the scaler and the target encoder are both fitted on the whole
series before any fold exists, so every fold's training half has already seen
the statistics of its own future.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

LAGS = (1, 2, 3, 24, 168)
TARGET = "demand"


def add_lags(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values("timestamp").copy()
    for lag in LAGS:
        out["lag_%d" % lag] = out[TARGET].shift(lag)
    out["rolling_24"] = out[TARGET].rolling(24).mean()
    return out.dropna()


def build_matrix(csv_path: str):
    frame = add_lags(pd.read_csv(csv_path))
    columns = ["lag_%d" % lag for lag in LAGS] + ["rolling_24"]

    scaler = StandardScaler()
    features = scaler.fit_transform(frame[columns])

    target_scaler = MinMaxScaler()
    target = target_scaler.fit_transform(frame[[TARGET]]).ravel()

    return features, target, scaler, target_scaler
