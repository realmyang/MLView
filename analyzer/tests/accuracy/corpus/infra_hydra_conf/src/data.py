"""Data loading, configured entirely from `conf/data/*.yaml`.

Correct on purpose: the split happens first, the scaler is fitted on the
training rows only, the training loader's `shuffle=` comes from the config
(where it is `true`) and the validation loader never shuffles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

TARGET = "label"


def load_frame(csv: str) -> pd.DataFrame:
    return pd.read_csv(csv)


def build_loaders(cfg):
    frame = load_frame(cfg.data.csv)
    labels = frame[TARGET].to_numpy(dtype="int64")
    features = frame.drop(columns=[TARGET]).to_numpy(dtype="float32")

    x_train, x_val, y_train, y_val = train_test_split(
        features, labels, test_size=cfg.data.val_fraction,
        random_state=cfg.seed, stratify=labels)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train)
    x_val = scaler.transform(x_val)

    train_set = _tensors(x_train, y_train)
    val_set = _tensors(x_val, y_val)

    train_loader = DataLoader(train_set, batch_size=cfg.data.batch_size,
                              shuffle=cfg.data.shuffle,
                              num_workers=cfg.data.num_workers,
                              drop_last=True)
    val_loader = DataLoader(val_set, batch_size=cfg.data.batch_size,
                            shuffle=False,
                            num_workers=cfg.data.num_workers)
    return train_loader, val_loader


def _tensors(x: np.ndarray, y: np.ndarray) -> TensorDataset:
    return TensorDataset(torch.from_numpy(x).float().view(-1, 3, 32, 32),
                         torch.from_numpy(y).long())
