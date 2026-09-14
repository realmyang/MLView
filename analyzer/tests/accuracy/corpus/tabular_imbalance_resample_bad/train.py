"""The same fraud table, resampled before it is split.

Planted defects, in the order they appear:

* the imputer and the power transform are fitted on the whole feature matrix
  before any split exists;
* ADASYN then oversamples that whole matrix, so a synthetic row interpolated
  from two training neighbours can land in the test half - and so can a
  duplicate of a training row;
* the split has no `random_state=` and nothing seeds `random` or numpy;
* `cross_val_score` is handed a bare estimator over the matrix that was already
  imputed, transformed and resampled outside the loop;
* the decision threshold is swept against the *test* labels and the best one is
  kept, which is model selection on the reported set;
* accuracy is then computed from the probability column rather than from the
  decision, and the reported AUC comes from hard labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from imblearn.over_sampling import ADASYN
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import PowerTransformer

TARGET = "is_fraud"
NUMERIC = ["amount", "hour_of_day", "days_since_last_txn", "merchant_risk"]
THRESHOLDS = np.linspace(0.05, 0.95, 19)


def prepare(csv_path: str):
    frame = pd.read_csv(csv_path)

    labels = frame[TARGET]
    features = frame[NUMERIC]

    imputer = SimpleImputer(strategy="mean")
    features = imputer.fit_transform(features)

    power = PowerTransformer(method="yeo-johnson")
    features = power.fit_transform(features)

    sampler = ADASYN(n_neighbors=5)
    features, labels = sampler.fit_resample(features, labels)

    train_x, test_x, train_y, test_y = train_test_split(features, labels,
                                                        test_size=0.25)
    return train_x, test_x, train_y, test_y, features, labels


def quick_baseline(features, labels):
    return cross_val_score(LogisticRegression(max_iter=2000), features, labels,
                           cv=5, scoring="average_precision")


def fit_model(train_x, train_y):
    model = RandomForestClassifier(n_estimators=400, class_weight="balanced")
    model.fit(train_x, train_y)
    return model


def tune_threshold_on_test(model, test_x, test_y) -> float:
    scores = model.predict_proba(test_x)[:, 1]
    best_threshold, best_f1 = 0.5, -1.0
    for threshold in THRESHOLDS:
        decisions = (scores >= threshold).astype(int)
        value = f1_score(test_y, decisions)
        if value > best_f1:
            best_threshold, best_f1 = float(threshold), float(value)
    return best_threshold


def main(csv_path: str = "data/transactions.csv") -> dict:
    train_x, test_x, train_y, test_y, features, labels = prepare(csv_path)

    baseline = quick_baseline(features, labels)
    model = fit_model(train_x, train_y)
    threshold = tune_threshold_on_test(model, test_x, test_y)

    probabilities = model.predict_proba(test_x)[:, 1]
    hard_labels = model.predict(test_x)

    return {
        "roc_auc": float(roc_auc_score(test_y, hard_labels)),
        "accuracy": float(accuracy_score(test_y, probabilities)),
        "threshold": threshold,
        "cv_average_precision": float(np.mean(baseline)),
    }


if __name__ == "__main__":
    print(main())
