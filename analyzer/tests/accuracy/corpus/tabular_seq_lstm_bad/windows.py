"""The same sliding windows, built in the wrong order.

Planted defects:

* `StandardScaler` is fitted on the whole series - every mean and variance the
  model trains against already contains the evaluation weeks;
* the windows are then cut from that scaled matrix and handed to
  `train_test_split(shuffle=True)`, so an "unseen" window can begin one hour
  after a training window ends and share 167 of its 168 rows with it;
* the split carries no `random_state=`, so the number moves every run.

The file is deliberately explicit about the series being temporal - it parses
dates and sorts by them - because that is what makes the random split a
question worth asking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
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


def scale_everything(frame: pd.DataFrame) -> np.ndarray:
    scaler = StandardScaler()
    matrix = scaler.fit_transform(frame[FEATURES])
    return matrix


def cut_windows(matrix: np.ndarray):
    target_index = FEATURES.index(TARGET)
    histories, futures = [], []
    for start in range(len(matrix) - LOOKBACK - HORIZON + 1):
        middle = start + LOOKBACK
        histories.append(matrix[start:middle, :])
        futures.append(matrix[middle:middle + HORIZON, target_index])
    return np.asarray(histories, dtype=np.float32), np.asarray(futures, dtype=np.float32)


class ArrayWindows(Dataset):
    def __init__(self, histories, futures):
        self.histories = histories
        self.futures = futures

    def __len__(self) -> int:
        return len(self.histories)

    def __getitem__(self, index: int):
        return (torch.from_numpy(self.histories[index]),
                torch.from_numpy(self.futures[index]))


def build_datasets(frame: pd.DataFrame):
    matrix = scale_everything(frame)
    histories, futures = cut_windows(matrix)

    train_h, test_h, train_f, test_f = train_test_split(histories, futures,
                                                        test_size=0.2,
                                                        shuffle=True)
    return ArrayWindows(train_h, train_f), ArrayWindows(test_h, test_f)
