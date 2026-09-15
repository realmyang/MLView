"""The split helper, in its own module so the cut is a cross-file question.

`chronological_split` takes the arrays and returns two disjoint halves without
shuffling anything: the rows are already in time order, so the last 20% is the
future and it is the holdout. Nothing here fits a transformer, so there is no
leak to find; the module exists to make the *order* of the pipeline explicit —
the split happens before `tf.data` ever sees the rows.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def chronological_split(features: np.ndarray, labels: np.ndarray,
                        holdout: float = 0.2
                        ) -> Tuple[Tuple[np.ndarray, np.ndarray],
                                   Tuple[np.ndarray, np.ndarray]]:
    if not 0.0 < holdout < 1.0:
        raise ValueError("holdout must be a fraction, got %r" % (holdout,))
    cut = int(len(features) * (1.0 - holdout))
    x_train, x_val = features[:cut], features[cut:]
    y_train, y_val = labels[:cut], labels[cut:]
    return (x_train, y_train), (x_val, y_val)


def standardize(x_train: np.ndarray, x_val: np.ndarray
                ) -> Tuple[np.ndarray, np.ndarray]:
    """Statistics from the training half only, applied to both."""
    mean = x_train.mean(axis=0, keepdims=True)
    std = x_train.std(axis=0, keepdims=True) + 1e-8
    return (x_train - mean) / std, (x_val - mean) / std
