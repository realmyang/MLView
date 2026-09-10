# MLVIEW-EXPECT: MLV602 confidence>=0.7
# MLVIEW-EXPECT: MLV602 confidence>=0.7
"""H5: two unseeded splits in a workspace with no global seed, so both reach
`certain` and both earn a mechanical edit - one `random_state=`, one
`generator=`.

`analyzer/tests/fixtures/rules/MLV602_bad.py` deliberately does **not** get one:
it seeds globally, which de-rates the finding to `possible`, and `ctx.issue`
drops the edit there. The two fixtures together are the gate on "no fix below
the likely bucket".

The sklearn call is written across two lines with its last argument on the
second, which is where "append after the last argument" is not the same as
"insert before the closing paren".
"""
import numpy as np
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import TensorDataset, random_split


def sklearn_split(path: str):
    raw = np.load(path)
    X_train, X_test, y_train, y_test = train_test_split(
        raw["features"], raw["labels"], test_size=0.2)
    return X_train, X_test, y_train, y_test


def torch_split(dataset: TensorDataset):
    train_ds, val_ds = random_split(dataset, [45000, 5000])
    return train_ds, val_ds
