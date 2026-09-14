"""The feature registry: it holds the frame it was constructed with.

Planted defect: `FeatureStore` is handed the **whole** table in `__init__`, and
`materialise()` fits the scaler and the encoder on `self.frame` before handing
the result to `stratified_split`. Nothing in this file mentions a test set, so
the mistake reads as ordinary code until you follow `self.frame` back to the
job that constructed the object.
"""
from __future__ import annotations

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from .splits import stratified_split

NUMERIC = ["balance", "n_logins_30d", "days_since_signup", "n_tickets"]
CATEGORICAL = ["plan", "region", "acquisition_channel"]


class FeatureStore:
    def __init__(self, frame: pd.DataFrame, target: str):
        self.frame = frame
        self.target = target
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value",
                                      unknown_value=-1)

    def numeric_block(self):
        block = self.frame[NUMERIC]
        imputed = self.imputer.fit_transform(block)
        return self.scaler.fit_transform(imputed)

    def categorical_block(self):
        return self.encoder.fit_transform(self.frame[CATEGORICAL])

    def materialise(self):
        import numpy as np

        labels = self.frame[self.target]
        matrix = np.hstack([self.numeric_block(), self.categorical_block()])
        return stratified_split(matrix, labels)

    def transform(self, frame: pd.DataFrame):
        import numpy as np

        numeric = self.scaler.transform(self.imputer.transform(frame[NUMERIC]))
        categorical = self.encoder.transform(frame[CATEGORICAL])
        return np.hstack([numeric, categorical])
