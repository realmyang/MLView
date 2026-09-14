"""Lag features for the same hourly load forecast - the defective twin.

`add_rolling` aggregates the target column itself instead of a shifted copy, so
`roll_mean_24` at time t contains the value at time t. The model can read its
own answer out of the feature, and the reported MAE is the rounding error of
that arithmetic rather than a forecast.
"""
from __future__ import annotations

import pandas as pd

TARGET = "load_mw"
TIMESTAMP = "timestamp"
LAGS = (1, 2, 3, 24, 168)
WINDOWS = (24, 168)


def read_series(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=[TIMESTAMP])
    return frame.sort_values(TIMESTAMP).reset_index(drop=True)


def add_lags(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for lag in LAGS:
        out["lag_%d" % lag] = out[TARGET].shift(lag)
    return out


def add_rolling(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for window in WINDOWS:
        out["roll_mean_%d" % window] = out[TARGET].rolling(window).mean()
    out["expanding_mean"] = out[TARGET].expanding().mean()
    return out


def add_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["hour"] = out[TIMESTAMP].dt.hour
    out["dayofweek"] = out[TIMESTAMP].dt.dayofweek
    return out


def build(csv_path: str) -> pd.DataFrame:
    frame = add_calendar(add_rolling(add_lags(read_series(csv_path))))
    return frame.fillna(method="bfill")


def feature_columns(frame: pd.DataFrame) -> list:
    return [c for c in frame.columns if c not in (TARGET, TIMESTAMP)]
