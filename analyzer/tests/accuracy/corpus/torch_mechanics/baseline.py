"""A tabular baseline over the hourly telemetry that accompanies the images.

Planted defects: an hourly series with lag features is shuffled into a random
train/test split; accuracy is computed on the probability matrix rather than on
predicted classes; and the ROC AUC is handed hard 0/1 predictions.
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

LAGS = (1, 24, 168)
TARGET = "failed"
SEED = 5


def build_frame(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp")
    for lag in LAGS:
        frame["lag_%d" % lag] = frame["throughput"].shift(lag)
    return frame.dropna()


def run(csv_path: str = "data/telemetry.csv"):
    frame = build_frame(csv_path)
    columns = ["lag_%d" % lag for lag in LAGS] + ["throughput"]

    train_x, test_x, train_y, test_y = train_test_split(
        frame[columns], frame[TARGET], test_size=0.2, random_state=SEED)

    model = RandomForestClassifier(n_estimators=300, random_state=SEED)
    model.fit(train_x, train_y)

    probabilities = model.predict_proba(test_x)
    predictions = model.predict(test_x)
    return (accuracy_score(test_y, probabilities),
            roc_auc_score(test_y, predictions))
