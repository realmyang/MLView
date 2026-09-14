"""The offline training job.

It reads the table, hands the whole thing to the feature store, and asks for a
split. The store fits three transformers on that whole table first - see
`store/registry.py` - so the scaler's means, the imputer's medians and the
encoder's category codes all carry the held-out rows.
"""
from __future__ import annotations

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from store.registry import FeatureStore
from store.splits import SEED

TARGET = "churned"


def load(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def run(csv_path: str = "data/accounts.csv") -> dict:
    frame = load(csv_path)
    store = FeatureStore(frame, TARGET)
    train_x, test_x, train_y, test_y = store.materialise()

    model = HistGradientBoostingClassifier(max_iter=400, random_state=SEED)
    model.fit(train_x, train_y)

    scores = model.predict_proba(test_x)[:, 1]
    joblib.dump({"model": model, "store": store}, "artifacts/churn.joblib")
    return {"roc_auc": float(roc_auc_score(test_y, scores))}


if __name__ == "__main__":
    print(run())
