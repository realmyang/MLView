"""Data loading. Planted: the scaler is fitted before the split, and the same
untransformed features are handed to a cross-validated baseline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

from registry import register

FEATURES = [f"f{i}" for i in range(32)]
TARGET = "y"


@register("dataset", "csv")
def csv_dataset(path: str = "data/experiment.csv"):
    frame = pd.read_csv(path)
    features = frame[FEATURES].to_numpy(dtype="float32")
    labels = frame[TARGET].to_numpy()

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    train_x, test_x, train_y, test_y = train_test_split(scaled, labels, test_size=0.25)
    return train_x, test_x, train_y, test_y


def baseline_score(path: str = "data/experiment.csv"):
    frame = pd.read_csv(path)
    features = StandardScaler().fit_transform(frame[FEATURES])
    return cross_val_score(LogisticRegression(max_iter=500), features,
                           frame[TARGET], cv=5)


def loaders(train_x, test_x, train_y, test_y, batch_size: int = 64):
    train = TensorDataset(torch.tensor(train_x), torch.tensor(train_y).long())
    test = TensorDataset(torch.tensor(test_x), torch.tensor(test_y).long())
    return (DataLoader(train, batch_size=batch_size, shuffle=True),
            DataLoader(test, batch_size=batch_size))
