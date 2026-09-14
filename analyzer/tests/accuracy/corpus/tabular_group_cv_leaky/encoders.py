"""The same two transformers as the clean twin.

Neither of these classes is defective. `fit` learns state from the rows it was
handed and `transform` applies it - the contract a `Pipeline` needs. Every
defect in this project is at the *call sites* in `train.py`, which fit them on
the wrong rows; the classes themselves are here as a false-positive trap, so a
rule that blames the transformer rather than the call has something to be wrong
about.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin


class TargetEncoder(BaseEstimator, TransformerMixin):
    """Smoothed mean encoding for high-cardinality categorical columns."""

    def __init__(self, columns, smoothing: float = 20.0):
        self.columns = columns
        self.smoothing = smoothing

    def fit(self, X, y=None):
        frame = pd.DataFrame(X).reset_index(drop=True)
        target = pd.Series(np.asarray(y, dtype=float))
        self.prior_ = float(target.mean())
        self.maps_ = {}
        for column in self.columns:
            stats = target.groupby(frame[column]).agg(["mean", "count"])
            weight = stats["count"] / (stats["count"] + self.smoothing)
            self.maps_[column] = weight * stats["mean"] + (1.0 - weight) * self.prior_
        return self

    def transform(self, X):
        frame = pd.DataFrame(X).copy()
        for column in self.columns:
            frame[column] = frame[column].map(self.maps_[column]).fillna(self.prior_)
        return frame


class FrequencyEncoder(BaseEstimator, TransformerMixin):
    """Replace a category by how often it was seen during `fit`."""

    def __init__(self, columns):
        self.columns = columns

    def fit(self, X, y=None):
        frame = pd.DataFrame(X)
        self.counts_ = {c: frame[c].value_counts(normalize=True)
                        for c in self.columns}
        return self

    def transform(self, X):
        frame = pd.DataFrame(X).copy()
        for column in self.columns:
            frame[column] = frame[column].map(self.counts_[column]).fillna(0.0)
        return frame
