# MLVIEW-EXPECT-NONE: MLV602
"""The trap: KFold and TimeSeriesSplit take no random_state and need none -
KFold does not shuffle unless asked, and TimeSeriesSplit is chronological. The
two genuinely random splits are pinned explicitly."""
import numpy as np
import torch
from sklearn.model_selection import (KFold, TimeSeriesSplit, train_test_split)
from torch.utils.data import TensorDataset, random_split


def splits(path: str, dataset: TensorDataset):
    np.random.seed(0)
    torch.manual_seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)
    folds = KFold(n_splits=5)
    chronological = TimeSeriesSplit(n_splits=5)
    train_ds, val_ds = random_split(
        dataset, [45000, 5000], generator=torch.Generator().manual_seed(42))
    return X_train, X_test, y_train, y_test, folds, chronological, train_ds, val_ds
