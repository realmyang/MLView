"""The `fit_model` task. Correct in itself — it only reads what prepare wrote.

There is no transformer fitted here, no split and no test data: the task loads
the training arrays the upstream task saved, fits one estimator inside a
`Pipeline`, cross-validates it on the training rows only, and writes the model.
Any leakage finding anchored in this file is a false positive; the leak this
project carries lives in `prepare.py`.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

FEATURE_ROOT = Path("/opt/airflow/data/churn")
MODEL_ROOT = Path("/opt/airflow/models/churn")


def build_estimator(seed: int) -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
            early_stopping=True, validation_fraction=0.15,
            random_state=seed)),
    ])


def fit_model(snapshot: str, seed: int) -> Path:
    source = FEATURE_ROOT / snapshot
    x_train = np.load(source / "x_train.npy")
    y_train = np.load(source / "y_train.npy")

    estimator = build_estimator(seed)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    scores = cross_val_score(estimator, x_train, y_train, cv=folds,
                             scoring="roc_auc", n_jobs=-1)
    print("cv auc %.4f +/- %.4f" % (scores.mean(), scores.std()))

    estimator.fit(x_train, y_train)

    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    target = MODEL_ROOT / ("%s.joblib" % snapshot)
    joblib.dump(estimator, target)
    return target
