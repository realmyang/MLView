"""DVC stage 1 — turn the raw meter export into a lagged feature table.

Every number in this file comes out of `params.yaml`: the date column, the
target column, the resample rule, the lag list and the rolling windows. Nothing
is fitted here and nothing is split here, so nothing here can leak. The lags and
the rolling means are computed with `shift()` first, so no window includes the
row it is a feature for.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import yaml

PARAMS_PATH = Path("params.yaml")


def load_params(path: Path = PARAMS_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_raw(path: str, date_column: str) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=[date_column])
    frame = frame.sort_values(date_column).reset_index(drop=True)
    return frame.set_index(date_column)


def add_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["hour"] = frame.index.hour
    frame["dayofweek"] = frame.index.dayofweek
    frame["month"] = frame.index.month
    frame["is_weekend"] = (frame.index.dayofweek >= 5).astype(int)
    return frame


def add_lags(frame: pd.DataFrame, target: str, lags, windows) -> pd.DataFrame:
    frame = frame.copy()
    for lag in lags:
        frame["lag_%d" % lag] = frame[target].shift(lag)
    for window in windows:
        frame["roll_mean_%d" % window] = (
            frame[target].shift(1).rolling(window).mean())
        frame["roll_std_%d" % window] = (
            frame[target].shift(1).rolling(window).std())
    return frame.dropna()


def main() -> None:
    params = load_params()
    base = params["base"]
    settings = params["prepare"]

    frame = read_raw(base["raw_path"], settings["date_column"])
    frame = frame.resample(settings["resample"]).mean()
    frame = add_calendar(frame)
    frame = add_lags(frame, settings["target_column"],
                     settings["lags"], settings["rolling_windows"])

    out = Path(base["interim_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out)
    print("prepared %d rows, %d columns" % frame.shape)


if __name__ == "__main__":
    main()
