"""Two hand-written transformers and one stateless one.

`WinsorizingTransformer` and `RareCategoryGrouper` both learn their state in
`fit` and apply it in `transform`, which is the contract that lets a `Pipeline`
refit them per fold. They are in the corpus as a false-positive trap: a rule
that keys on "`.fit(` was called on something that looks like a feature matrix"
fires on every correct custom transformer ever written, because learning from
the data you were handed is *what fit means*.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import FunctionTransformer


class WinsorizingTransformer(BaseEstimator, TransformerMixin):
    """Clip each column to the quantiles learned on the rows it was fitted on."""

    def __init__(self, lower: float = 0.01, upper: float = 0.99):
        self.lower = lower
        self.upper = upper

    def fit(self, X, y=None):
        frame = pd.DataFrame(X)
        self.lower_ = frame.quantile(self.lower).to_numpy()
        self.upper_ = frame.quantile(self.upper).to_numpy()
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lower_, self.upper_)


class RareCategoryGrouper(BaseEstimator, TransformerMixin):
    """Fold categories seen fewer than `min_count` times into one bucket."""

    def __init__(self, min_count: int = 25, other: str = "__other__"):
        self.min_count = min_count
        self.other = other

    def fit(self, X, y=None):
        frame = pd.DataFrame(X)
        self.keep_ = {}
        for column in frame.columns:
            counts = frame[column].value_counts()
            self.keep_[column] = set(counts[counts >= self.min_count].index)
        return self

    def transform(self, X):
        frame = pd.DataFrame(X).copy()
        for column, keep in self.keep_.items():
            frame[column] = frame[column].where(frame[column].isin(keep),
                                                self.other)
        return frame


def log1p_columns(X):
    return np.log1p(np.clip(np.asarray(X, dtype=float), a_min=0.0, a_max=None))


def make_log_transformer() -> FunctionTransformer:
    return FunctionTransformer(log1p_columns, feature_names_out="one-to-one")
