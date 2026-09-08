"""A gradient-boosting tabular baseline with no torch anywhere in it.

Planted defects: the encoder and the scaler are fitted on the full frame before
the split, the scaler is then re-fitted on the held-out half, the split has no
random_state and nothing seeds the estimator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

CATEGORICAL = ["product", "channel", "segment"]
NUMERIC = ["amount", "tenure_days", "n_claims"]
TARGET = "lapsed"


def prepare(csv_path: str):
    frame = pd.read_csv(csv_path)

    encoder = OrdinalEncoder()
    encoded = encoder.fit_transform(frame[CATEGORICAL])

    scaler = StandardScaler()
    scaled = scaler.fit_transform(frame[NUMERIC])

    features = np.hstack([encoded, scaled])
    labels = frame[TARGET].to_numpy()
    train_x, test_x, train_y, test_y = train_test_split(features, labels, test_size=0.2)
    return train_x, test_x, train_y, test_y, scaler


def run(csv_path: str = "data/policies.csv"):
    train_x, test_x, train_y, test_y, scaler = prepare(csv_path)

    test_x = scaler.fit_transform(test_x)

    model = xgb.XGBClassifier(n_estimators=400, max_depth=6, learning_rate=0.05)
    model.fit(train_x, train_y)
    return roc_auc_score(test_y, model.predict_proba(test_x)[:, 1])


if __name__ == "__main__":
    print(run())
