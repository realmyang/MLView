"""GRAPH-R2: the pandas families that change what the data means.

`knowledge/other_tbl.FRAME_OP_METHODS` folds a shape-preserving hop away on
purpose (`.copy()` is not a box). `knowledge/pandas_tbl.py` draws the two
families that are not shape-preserving in any useful sense: the lag / window
block where a time-series feature matrix is built, and the regroup / join where
rows arrive from somewhere else.
"""
from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import StandardScaler


def lag_features(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path).sort_values("timestamp")
    frame["lag_1"] = frame["demand"].shift(1)
    frame["roll_24"] = frame["demand"].shift(1).rolling(24).mean()
    frame["delta"] = frame["demand"].diff()
    frame["growth"] = frame["demand"].pct_change()
    return frame.dropna()


def regrouped(csv_path: str, lookup_path: str) -> pd.DataFrame:
    frame = pd.read_parquet(csv_path)
    lookup = pd.read_table(lookup_path)
    joined = frame.merge(lookup, on="store_id")
    per_store = joined.groupby("store_id").mean()
    return per_store


def indexed(csv_path: str):
    """`df.loc[...]` / `df.iloc[...]` are the ordinary way to cut a feature
    matrix, and the indexer used to stop the frame's tags dead: `dotted_text`
    answers `frame.loc`, a name nothing binds."""
    frame = pd.read_csv(csv_path)
    features = frame.loc[:, ["lag_1", "roll_24"]].to_numpy()
    target = frame.iloc[:, -1].to_numpy()
    scaled = StandardScaler().fit_transform(features)
    return scaled, target


def published(frame: pd.DataFrame, out_path: str) -> None:
    frame.to_parquet(out_path)
