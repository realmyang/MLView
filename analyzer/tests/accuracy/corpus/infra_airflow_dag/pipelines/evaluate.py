"""The `score_holdout` task. Scores the held-out rows exactly once.

`roc_auc_score` is fed `predict_proba(...)[:, 1]` — a score, not a hard label —
and `f1_score` is fed `predict(...)`, which is what those two respectively ask
for. Nothing here fits anything, so nothing here can leak.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import (average_precision_score, f1_score,
                             precision_recall_fscore_support, roc_auc_score)

FEATURE_ROOT = Path("/opt/airflow/data/churn")
MODEL_ROOT = Path("/opt/airflow/models/churn")
METRIC_ROOT = Path("/opt/airflow/metrics/churn")


def score_holdout(snapshot: str) -> dict:
    source = FEATURE_ROOT / snapshot
    x_hold = np.load(source / "x_hold.npy")
    y_hold = np.load(source / "y_hold.npy")

    model = joblib.load(MODEL_ROOT / ("%s.joblib" % snapshot))
    scores = model.predict_proba(x_hold)[:, 1]
    predictions = model.predict(x_hold)

    precision, recall, f_beta, _support = precision_recall_fscore_support(
        y_hold, predictions, average="binary", zero_division=0)

    metrics = {
        "auc": float(roc_auc_score(y_hold, scores)),
        "average_precision": float(average_precision_score(y_hold, scores)),
        "f1": float(f1_score(y_hold, predictions)),
        "precision": float(precision),
        "recall": float(recall),
        "f_beta": float(f_beta),
    }

    METRIC_ROOT.mkdir(parents=True, exist_ok=True)
    (METRIC_ROOT / ("%s.json" % snapshot)).write_text(json.dumps(metrics))
    return metrics
