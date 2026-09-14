"""The `build_features` task — and the one planted defect in this project.

The scaler is fitted on the **whole** feature matrix at line 49 and the
train/holdout cut is made at line 51, two lines later, from the scaled frame.
Every holdout row has therefore contributed its mean and variance to the
transform that the model is trained under, and the holdout AUC the DAG promotes
on is optimistic by an amount nobody can measure after the fact.

This is the commonest real spelling of the defect: the leak is not in a model
file, it is in an ETL task that runs hours before the model file does, and the
`train` task downstream only ever sees the artefact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

FEATURE_ROOT = Path("/opt/airflow/data/churn")
NUMERIC = ["tenure_months", "monthly_charge", "total_charge",
           "support_tickets", "avg_session_minutes"]


def _read_snapshot(snapshot: str) -> pd.DataFrame:
    """A synthetic stand-in for the warehouse extract this task really runs."""
    rng = np.random.default_rng(abs(hash(snapshot)) % (2 ** 32))
    frame = pd.DataFrame({
        "tenure_months": rng.integers(1, 72, size=5000),
        "monthly_charge": rng.normal(70, 25, size=5000),
        "total_charge": rng.normal(2400, 900, size=5000),
        "support_tickets": rng.poisson(1.2, size=5000),
        "avg_session_minutes": rng.gamma(2.0, 8.0, size=5000),
        "churned": (rng.random(5000) > 0.74).astype(int),
    })
    return frame


def build_features(snapshot: str, seed: int) -> Tuple[Path, Path]:
    """Scale, then split — which is the wrong order, and the planted defect."""
    frame = _read_snapshot(snapshot)
    labels = frame["churned"]
    features = frame[NUMERIC]

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    x_train, x_hold, y_train, y_hold = train_test_split(
        scaled, labels, test_size=0.25, random_state=seed, stratify=labels)

    out = FEATURE_ROOT / snapshot
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "x_train.npy", x_train)
    np.save(out / "y_train.npy", np.asarray(y_train))
    np.save(out / "x_hold.npy", x_hold)
    np.save(out / "y_hold.npy", np.asarray(y_hold))
    return out / "x_train.npy", out / "x_hold.npy"
