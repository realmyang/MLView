"""Probability calibration and threshold tuning, done on a third split.

This file is in the corpus as a false-positive trap. Three things happen here
that *look* like leakage to a pattern matcher and are the correct procedure:

* an isotonic calibrator is **fitted on the calibration split** - that is what a
  calibration split is for, and `cv="prefit"` says the base estimator was fitted
  elsewhere;
* the decision threshold is **chosen on the calibration split** by sweeping
  candidate thresholds against the F1 it produces;
* the test split is used exactly once, at the end, and only through `transform`
  / `predict_proba`.

Nothing is ever fitted on `test_x`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (brier_score_loss, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEED = 99
TARGET = "fraud"
THRESHOLDS = np.linspace(0.05, 0.95, 19)


def three_way_split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])

    train_x, rest_x, train_y, rest_y = train_test_split(
        features, labels, test_size=0.4, stratify=labels, random_state=SEED)
    calib_x, test_x, calib_y, test_y = train_test_split(
        rest_x, rest_y, test_size=0.5, stratify=rest_y, random_state=SEED)
    return train_x, train_y, calib_x, calib_y, test_x, test_y


def fit_base(train_x, train_y) -> Pipeline:
    base = Pipeline(steps=[
        ("scale", StandardScaler()),
        ("gbm", HistGradientBoostingClassifier(max_iter=300, random_state=SEED)),
    ])
    base.fit(train_x, train_y)
    return base


def calibrate(base: Pipeline, calib_x, calib_y) -> CalibratedClassifierCV:
    calibrator = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
    calibrator.fit(calib_x, calib_y)
    return calibrator


def choose_threshold(calibrator, calib_x, calib_y) -> float:
    probabilities = calibrator.predict_proba(calib_x)[:, 1]
    best_threshold, best_score = 0.5, -1.0
    for threshold in THRESHOLDS:
        decisions = (probabilities >= threshold).astype(int)
        score = f1_score(calib_y, decisions)
        if score > best_score:
            best_threshold, best_score = float(threshold), float(score)
    return best_threshold


def report(calibrator, test_x, test_y, threshold: float) -> dict:
    probabilities = calibrator.predict_proba(test_x)[:, 1]
    decisions = (probabilities >= threshold).astype(int)
    fraction, mean_predicted = calibration_curve(test_y, probabilities, n_bins=10)
    return {
        "roc_auc": float(roc_auc_score(test_y, probabilities)),
        "brier": float(brier_score_loss(test_y, probabilities)),
        "f1": float(f1_score(test_y, decisions)),
        "precision": float(precision_score(test_y, decisions)),
        "recall": float(recall_score(test_y, decisions)),
        "calibration_gap": float(np.abs(fraction - mean_predicted).max()),
    }


def main(csv_path: str = "data/transactions.csv") -> dict:
    frame = pd.read_csv(csv_path)
    train_x, train_y, calib_x, calib_y, test_x, test_y = three_way_split(frame)

    base = fit_base(train_x, train_y)
    calibrator = calibrate(base, calib_x, calib_y)
    threshold = choose_threshold(calibrator, calib_x, calib_y)

    result = report(calibrator, test_x, test_y, threshold)
    result["threshold"] = threshold
    return result


if __name__ == "__main__":
    print(main())
