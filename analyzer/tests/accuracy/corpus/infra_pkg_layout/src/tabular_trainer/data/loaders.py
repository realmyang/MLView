"""Reading the CSV and turning it into two DataLoaders.

Planted defect: `StandardScaler().fit_transform` runs over the whole feature
matrix three lines before `train_test_split`, so the held-out rows contributed
their mean and variance to the scaling every training row was normalised with.
(MLV101; and the split takes no `random_state=`, which is MLV602.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from ..config import TrainConfig
from ..utils.io import resolve_path
from ..utils.logging import get_logger

log = get_logger(__name__)


def read_frame(cfg: TrainConfig) -> pd.DataFrame:
    path = resolve_path(cfg.csv_path)
    log.info("reading %s", path)
    return pd.read_csv(path)


def build_loaders(cfg: TrainConfig):
    frame = read_frame(cfg)
    labels = frame[cfg.target].to_numpy(dtype="int64")
    features = frame[cfg.features].to_numpy(dtype="float32")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    x_train, x_test, y_train, y_test = train_test_split(
        scaled, labels, test_size=cfg.test_size, stratify=labels)

    train_loader = DataLoader(_dataset(x_train, y_train),
                              batch_size=cfg.batch_size, shuffle=True,
                              num_workers=cfg.num_workers, drop_last=True)
    test_loader = DataLoader(_dataset(x_test, y_test),
                             batch_size=cfg.batch_size, shuffle=False,
                             num_workers=cfg.num_workers)
    log.info("train=%d test=%d", len(x_train), len(x_test))
    return train_loader, test_loader, scaler


def _dataset(x: np.ndarray, y: np.ndarray) -> TensorDataset:
    return TensorDataset(torch.from_numpy(np.asarray(x)).float(),
                         torch.from_numpy(y).long())
