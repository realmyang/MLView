# MLVIEW-EXPECT: MLV602 line=17 confidence>=0.6 severity=low
# MLVIEW-EXPECT: MLV602 line=23 confidence>=0.6 severity=low
"""Two unseeded splits: a sklearn train_test_split and a torch random_split."""
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from torch.utils.data import TensorDataset, random_split


def sklearn_split(path: str):
    np.random.seed(0)
    torch.manual_seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    LogisticRegression(max_iter=200).fit(X_train, y_train)
    return X_test, y_test


def torch_split(dataset: TensorDataset):
    train_ds, val_ds = random_split(dataset, [45000, 5000])
    return train_ds, val_ds
