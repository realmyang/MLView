# MLVIEW-EXPECT-NONE: MLV602
"""H5: the clean twin of `MLV602_unseeded_bad.py` - both splits already carry
the keyword the mechanical edit would have appended, in the same position it
would have appended it.
"""
import numpy as np
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import TensorDataset, random_split


def sklearn_split(path: str):
    raw = np.load(path)
    X_train, X_test, y_train, y_test = train_test_split(
        raw["features"], raw["labels"], test_size=0.2, random_state=42)
    return X_train, X_test, y_train, y_test


def torch_split(dataset: TensorDataset):
    train_ds, val_ds = random_split(
        dataset, [45000, 5000], generator=torch.Generator().manual_seed(42))
    return train_ds, val_ds
