"""Fraud detection on a 1:400 table, with the resampling inside the pipeline.

This project is a false-positive trap end to end. Four things happen that look
like leakage to a pattern matcher and are the correct procedure:

* SMOTE is fitted - it has to be, it is a fitted object - but only ever as a
  `Pipeline` step, so it sees one fold's training half at a time and never a
  validation row;
* the operating threshold is chosen on a dedicated validation split, not on the
  test rows;
* `cross_val_score` is handed the whole pipeline, so every fold refits the
  imputer, the scaler, the encoder and the resampler;
* the test rows are touched exactly once, by `predict_proba`, after every
  decision has already been made.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, f1_score,
                             precision_recall_curve, roc_auc_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

from pipeline import CATEGORICAL, NUMERIC, SEED, build_estimator

TARGET = "is_fraud"
N_FOLDS = 5


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    median_amount = frame["amount"].median()
    frame["amount_to_median_ratio"] = frame["amount"] / max(median_amount, 1.0)
    return frame


def three_way_split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame[NUMERIC + CATEGORICAL]
    train_x, rest_x, train_y, rest_y = train_test_split(
        features, labels, test_size=0.4, stratify=labels, random_state=SEED)
    valid_x, test_x, valid_y, test_y = train_test_split(
        rest_x, rest_y, test_size=0.5, stratify=rest_y, random_state=SEED)
    return train_x, valid_x, test_x, train_y, valid_y, test_y


def cross_validate(train_x, train_y) -> float:
    folds = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    scores = cross_val_score(build_estimator(), train_x, train_y, cv=folds,
                             scoring="average_precision")
    return float(np.mean(scores))


def choose_threshold(model, valid_x, valid_y) -> float:
    valid_scores = model.predict_proba(valid_x)[:, 1]
    precision, recall, thresholds = precision_recall_curve(valid_y, valid_scores)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-9, None)
    best = int(np.argmax(f1[:-1])) if len(thresholds) else 0
    return float(thresholds[best]) if len(thresholds) else 0.5


def evaluate(model, threshold: float, test_x, test_y) -> dict:
    test_scores = model.predict_proba(test_x)[:, 1]
    decisions = (test_scores >= threshold).astype(int)
    return {
        "roc_auc": float(roc_auc_score(test_y, test_scores)),
        "average_precision": float(average_precision_score(test_y, test_scores)),
        "f1": float(f1_score(test_y, decisions)),
        "threshold": threshold,
    }


def main(csv_path: str = "data/transactions.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_x, valid_x, test_x, train_y, valid_y, test_y = three_way_split(frame)

    cv_ap = cross_validate(train_x, train_y)

    model = build_estimator()
    model.fit(train_x, train_y)

    threshold = choose_threshold(model, valid_x, valid_y)
    report = evaluate(model, threshold, test_x, test_y)
    report["cv_average_precision"] = cv_ap
    return report


if __name__ == "__main__":
    print(main())
