"""The nightly scoring job: the same store, `transform` only."""
from __future__ import annotations

import joblib
import pandas as pd


def score(csv_path: str = "data/accounts_today.csv",
          bundle_path: str = "artifacts/churn.joblib") -> pd.DataFrame:
    bundle = joblib.load(bundle_path)
    frame = pd.read_csv(csv_path)

    matrix = bundle["store"].transform(frame)
    frame["churn_score"] = bundle["model"].predict_proba(matrix)[:, 1]
    return frame[["account_id", "churn_score"]]


if __name__ == "__main__":
    print(score().head())
