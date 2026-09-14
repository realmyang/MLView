"""Unsupervised anomaly detection on machine telemetry, scored honestly.

Anomaly detection is the shape where leakage rules are most likely to be wrong,
because the fit really does take an unlabelled matrix and there really is no
`y` to hold out. Four things happen here that look suspicious and are correct:

* `IsolationForest`, `OneClassSVM` and `LocalOutlierFactor(novelty=True)` are
  each fitted on the *training* window only - the whole point of `novelty=True`
  is that the fitted object is then asked about rows it has never seen;
* the scaler lives inside a `Pipeline` with the detector, so nothing is fitted
  outside the training window;
* the contamination level is chosen on a labelled validation split, not on the
  test rows;
* the test rows reach `decision_function` and `predict` once each, after every
  decision has already been made.

`detect.py` also holds a supervised sanity check on the same split, so the file
carries a classifier, a threshold and three metrics without ever fitting
anything on the held-out half.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from sklearn.covariance import EllipticEnvelope
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import QuantileTransformer
from sklearn.svm import OneClassSVM

SEED = 505
LABEL = "is_fault"
SIGNALS = ["vibration_rms", "bearing_temp_c", "current_a", "spindle_load_pct",
           "acoustic_db"]
CONTAMINATIONS = (0.005, 0.01, 0.02, 0.05, 0.1)


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    return frame.dropna(subset=SIGNALS)


def three_way_split(frame: pd.DataFrame):
    labels = frame[LABEL]
    signals = frame[SIGNALS]
    train_x, rest_x, train_y, rest_y = train_test_split(
        signals, labels, test_size=0.4, stratify=labels, random_state=SEED)
    valid_x, test_x, valid_y, test_y = train_test_split(
        rest_x, rest_y, test_size=0.5, stratify=rest_y, random_state=SEED)
    return train_x, valid_x, test_x, train_y, valid_y, test_y


def build_forest(contamination: float) -> Pipeline:
    return Pipeline(steps=[
        ("quantile", QuantileTransformer(output_distribution="normal",
                                         random_state=SEED)),
        ("forest", IsolationForest(n_estimators=400,
                                   contamination=contamination,
                                   random_state=SEED, n_jobs=-1)),
    ])


def build_svm(nu: float) -> Pipeline:
    return Pipeline(steps=[
        ("quantile", QuantileTransformer(output_distribution="normal",
                                         random_state=SEED)),
        ("svm", OneClassSVM(kernel="rbf", nu=nu, gamma="scale")),
    ])


def build_lof(contamination: float) -> Pipeline:
    return Pipeline(steps=[
        ("quantile", QuantileTransformer(output_distribution="normal",
                                         random_state=SEED)),
        ("lof", LocalOutlierFactor(n_neighbors=40, novelty=True,
                                   contamination=contamination)),
    ])


def choose_contamination(train_x, valid_x, valid_y) -> dict:
    """Fit on the training window, score the validation window, keep the best."""
    leaderboard = {}
    for level in CONTAMINATIONS:
        detector = build_forest(level)
        detector.fit(train_x)
        flags = (detector.predict(valid_x) == -1).astype(int)
        leaderboard[level] = float(f1_score(valid_y, flags))
    best = max(leaderboard, key=leaderboard.get)
    return {"contamination": float(best), "validation_f1": leaderboard[best]}


def fit_ensemble(train_x, contamination: float) -> dict:
    forest = build_forest(contamination)
    forest.fit(train_x)

    svm = build_svm(nu=contamination)
    svm.fit(train_x)

    lof = build_lof(contamination)
    lof.fit(train_x)

    envelope = EllipticEnvelope(contamination=contamination, random_state=SEED)
    envelope.fit(train_x)

    return {"forest": forest, "svm": svm, "lof": lof, "envelope": envelope}


def evaluate(detectors: dict, test_x, test_y) -> dict:
    forest_scores = -detectors["forest"].decision_function(test_x)
    lof_scores = -detectors["lof"].decision_function(test_x)
    flags = (detectors["forest"].predict(test_x) == -1).astype(int)
    return {
        "forest_roc_auc": float(roc_auc_score(test_y, forest_scores)),
        "forest_average_precision": float(average_precision_score(test_y,
                                                                  forest_scores)),
        "lof_roc_auc": float(roc_auc_score(test_y, lof_scores)),
        "forest_f1": float(f1_score(test_y, flags)),
    }


def main(csv_path: str = "data/telemetry.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_x, valid_x, test_x, _train_y, valid_y, test_y = three_way_split(frame)

    chosen = choose_contamination(train_x, valid_x, valid_y)
    detectors = fit_ensemble(train_x, chosen["contamination"])

    report = evaluate(detectors, test_x, test_y)
    report.update(chosen)
    return report


if __name__ == "__main__":
    print(main())
