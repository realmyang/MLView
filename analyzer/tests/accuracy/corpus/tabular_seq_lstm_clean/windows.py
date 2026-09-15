"""Sliding windows over an hourly load series, cut by time before scaling.

The order of the three operations in `build_datasets` is the whole point:

1. sort by timestamp and cut chronologically, so the validation window is
   strictly later than the training window;
2. fit the scaler on the training window **only**, and `transform` the
   validation window with it;
3. window each half separately, so no window ever straddles the cut.

Doing (2) before (1) is the single commonest mistake in time-series code and is
what the defective twin of this project does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from torch.utils.data import Dataset

TARGET = "load_mw"
FEATURES = ["load_mw", "temperature_c", "is_holiday", "hour_sin", "hour_cos"]
LOOKBACK = 168
HORIZON = 24


def load_series(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["hour_sin"] = np.sin(2 * np.pi * frame["timestamp"].dt.hour / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["timestamp"].dt.hour / 24.0)
    return frame.dropna(subset=FEATURES)


def chronological_cut(frame: pd.DataFrame, valid_hours: int = 24 * 28):
    cutoff = len(frame) - valid_hours
    past = frame.iloc[:cutoff].reset_index(drop=True)
    future = frame.iloc[cutoff:].reset_index(drop=True)
    return past, future


class WindowDataset(Dataset):
    """`LOOKBACK` hours of features in, `HORIZON` hours of load out."""

    def __init__(self, matrix: np.ndarray, target_index: int,
                 lookback: int = LOOKBACK, horizon: int = HORIZON):
        self.matrix = np.asarray(matrix, dtype=np.float32)
        self.target_index = target_index
        self.lookback = lookback
        self.horizon = horizon

    def __len__(self) -> int:
        return max(0, len(self.matrix) - self.lookback - self.horizon + 1)

    def __getitem__(self, index: int):
        start = index
        middle = index + self.lookback
        end = middle + self.horizon
        history = self.matrix[start:middle, :]
        future = self.matrix[middle:end, self.target_index]
        return torch.from_numpy(history), torch.from_numpy(future)


def build_datasets(frame: pd.DataFrame):
    past, future = chronological_cut(frame)

    scaler = StandardScaler()
    train_matrix = scaler.fit_transform(past[FEATURES])
    valid_matrix = scaler.transform(future[FEATURES])

    target_index = FEATURES.index(TARGET)
    train_set = WindowDataset(train_matrix, target_index)
    valid_set = WindowDataset(valid_matrix, target_index)
    return train_set, valid_set, scaler
