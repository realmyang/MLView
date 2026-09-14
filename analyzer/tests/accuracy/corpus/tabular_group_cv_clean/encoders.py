"""Out-of-fold target encoding, written as a scikit-learn transformer.

`TargetEncoder` learns its category means in `fit` and applies them in
`transform`, which is the only contract that lets a `Pipeline` refit it on each
fold's own training rows. It is in the corpus as a false-positive trap for two
reasons at once:

* learning statistics from the rows you were handed is *what fit means*, so a
  rule that keys on "`.fit(` was called on a frame" fires on every correct
  custom transformer ever written;
* this particular transformer reads `y`, which is exactly the thing a leakage
  rule is watching for - and reading `y` inside `fit` is how target encoding is
  *supposed* to work.
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
            grouped = target.groupby(frame[column])
            stats = grouped.agg(["mean", "count"])
            weight = stats["count"] / (stats["count"] + self.smoothing)
            blended = weight * stats["mean"] + (1.0 - weight) * self.prior_
            self.maps_[column] = blended
        return self

    def transform(self, X):
        frame = pd.DataFrame(X).copy()
        for column in self.columns:
            mapped = frame[column].map(self.maps_[column])
            frame[column] = mapped.fillna(self.prior_)
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
