"""An MLflow-tracked credit-risk experiment.

The tracking is fine. The measurement is not, and that is the point of the
file: every number logged to MLflow below is computed wrongly, so the
experiment page shows a tidy, reproducible, wrong leaderboard.

Planted defects:

* the scaler fitted on the training half is **re-fitted** on the test half
  before scoring, so the test features are standardised by their own
  statistics;
* `roc_auc_score` is handed `model.predict(...)`, which is a hard 0/1 label -
  the ROC curve then has two points and the number is balanced accuracy wearing
  an AUC label;
* `accuracy_score` is handed the raw probability column instead of a decision,
  which scores a continuous vector against 0/1 labels.
"""
from __future__ import annotations

import mlflow
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

SEED = 64
TARGET = "default_12m"
EXPERIMENT = "credit-risk/baseline"


def load(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def prepare(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])
    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=0.2, stratify=labels, random_state=SEED)

    scaler = StandardScaler()
    train_x = scaler.fit_transform(train_x)
    test_x = scaler.fit_transform(test_x)
    return train_x, test_x, train_y, test_y


def run_trial(train_x, train_y, test_x, test_y, n_estimators: int) -> dict:
    with mlflow.start_run(nested=True):
        mlflow.log_param("n_estimators", n_estimators)
        mlflow.log_param("seed", SEED)

        model = RandomForestClassifier(n_estimators=n_estimators,
                                       random_state=SEED, n_jobs=-1)
        model.fit(train_x, train_y)

        decisions = model.predict(test_x)
        probabilities = model.predict_proba(test_x)[:, 1]

        metrics = {
            "roc_auc": float(roc_auc_score(test_y, decisions)),
            "accuracy": float(accuracy_score(test_y, probabilities)),
            "f1": float(f1_score(test_y, decisions)),
        }
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, artifact_path="model")
        return metrics


def main(csv_path: str = "data/loans.csv") -> pd.DataFrame:
    np.random.seed(SEED)
    mlflow.set_experiment(EXPERIMENT)

    frame = load(csv_path)
    train_x, test_x, train_y, test_y = prepare(frame)

    rows = []
    with mlflow.start_run(run_name="sweep"):
        for n_estimators in (100, 300, 600):
            row = run_trial(train_x, train_y, test_x, test_y, n_estimators)
            row["n_estimators"] = n_estimators
            rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(main())
