"""Lag and rolling features for an hourly load forecast.

Every window is shifted by at least one step before it is aggregated, so a row
never sees its own target. `dropna()` removes the warm-up rows the shifts
create rather than back-filling them, which would carry the future backwards.
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
    past = out[TARGET].shift(1)
    for window in WINDOWS:
        out["roll_mean_%d" % window] = past.rolling(window).mean()
        out["roll_std_%d" % window] = past.rolling(window).std()
    return out


def add_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["hour"] = out[TIMESTAMP].dt.hour
    out["dayofweek"] = out[TIMESTAMP].dt.dayofweek
    out["is_weekend"] = (out["dayofweek"] >= 5).astype(int)
    return out


def build(csv_path: str) -> pd.DataFrame:
    frame = add_calendar(add_rolling(add_lags(read_series(csv_path))))
    return frame.dropna().reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list:
    return [c for c in frame.columns if c not in (TARGET, TIMESTAMP)]
