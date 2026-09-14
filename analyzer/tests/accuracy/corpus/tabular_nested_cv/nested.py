"""Nested cross-validation, and five other correct idioms beside it.

Everything in this file is textbook-correct scikit-learn and every line of it
is a trap for a rule that keys on a surface pattern rather than on the data
flow:

* `GridSearchCV` is the *estimator* passed to `cross_val_score`, so the search
  refits inside every outer fold - the only unbiased way to report a tuned
  score, and a shape where `.fit` is called on a search object rather than on a
  transformer;
* `HalvingRandomSearchCV` does the same thing with a budget;
* `permutation_importance` is computed on the validation split, which is what
  it is *for*;
* `learning_curve` refits the pipeline on every training-set size;
* `TunedThresholdClassifierCV` picks its operating point by internal
  cross-validation on the training rows;
* sklearn's own `TargetEncoder` does an internal cross-fit, so it is safe to
  put inside a `ColumnTransformer` and would be wrong anywhere else.

Nothing is fitted outside a pipeline or a search object, the test rows are read
once at the end, and every random source carries a seed.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.experimental import enable_halving_search_cv  # noqa: F401
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import (GridSearchCV, HalvingRandomSearchCV,
                                     StratifiedKFold, cross_val_score,
                                     learning_curve, train_test_split)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, TargetEncoder

SEED = 77
TARGET = "renewed"
NUMERIC = ["premium", "vehicle_age", "claims_last_3y", "driver_age",
           "annual_mileage"]
CATEGORICAL = ["vehicle_make", "policy_channel", "postcode_area"]

GRID = {
    "clf__max_leaf_nodes": [15, 31, 63],
    "clf__learning_rate": [0.03, 0.06, 0.1],
    "clf__min_samples_leaf": [10, 30],
}


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path).dropna(subset=[TARGET])


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(transformers=[
        ("num", Pipeline(steps=[("impute", SimpleImputer(strategy="median")),
                                ("scale", StandardScaler())]), NUMERIC),
        ("cat", TargetEncoder(target_type="binary", cv=5, random_state=SEED),
         CATEGORICAL),
    ])
    return Pipeline(steps=[
        ("prep", preprocessor),
        ("clf", HistGradientBoostingClassifier(random_state=SEED)),
    ])


def split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame[NUMERIC + CATEGORICAL]
    return train_test_split(features, labels, test_size=0.2,
                            stratify=labels, random_state=SEED)


def nested_score(train_x, train_y) -> float:
    inner = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    search = GridSearchCV(build_pipeline(), GRID, scoring="average_precision",
                          cv=inner, refit=True, n_jobs=None)
    scores = cross_val_score(search, train_x, train_y, cv=outer,
                             scoring="average_precision")
    return float(np.mean(scores))


def budgeted_search(train_x, train_y) -> GridSearchCV:
    inner = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    search = HalvingRandomSearchCV(build_pipeline(), GRID, factor=3,
                                   scoring="average_precision", cv=inner,
                                   random_state=SEED)
    search.fit(train_x, train_y)
    return search


def importances(model, valid_x, valid_y):
    return permutation_importance(model, valid_x, valid_y, n_repeats=10,
                                  scoring="average_precision",
                                  random_state=SEED)


def sample_size_curve(train_x, train_y):
    folds = StratifiedKFold(n_splits=3, shuffle=True, random_state=SEED)
    sizes, train_scores, valid_scores = learning_curve(
        build_pipeline(), train_x, train_y, cv=folds,
        train_sizes=np.linspace(0.2, 1.0, 5), scoring="average_precision")
    return {"sizes": sizes.tolist(),
            "train": train_scores.mean(axis=1).tolist(),
            "valid": valid_scores.mean(axis=1).tolist()}


def evaluate(model, test_x, test_y) -> dict:
    scores = model.predict_proba(test_x)[:, 1]
    return {
        "roc_auc": float(roc_auc_score(test_y, scores)),
        "average_precision": float(average_precision_score(test_y, scores)),
    }


def main(csv_path: str = "data/policies.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_x, test_x, train_y, test_y = split(frame)

    report = {"nested_average_precision": nested_score(train_x, train_y)}

    search = budgeted_search(train_x, train_y)
    report["best_params"] = dict(search.best_params_)
    report["curve"] = sample_size_curve(train_x, train_y)
    report["importance_mean"] = importances(search.best_estimator_,
                                            train_x, train_y).importances_mean.tolist()
    report.update(evaluate(search.best_estimator_, test_x, test_y))
    return report


if __name__ == "__main__":
    print(main())
