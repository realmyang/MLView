"""A Kaggle-shaped tabular baseline, written the way it should be written.

Held-out integrity, step by step:

* the frame is engineered with row-wise functions only, then split once, with
  `stratify=` and a `random_state=`;
* every fitted transformer lives inside the `Pipeline`, so `StratifiedKFold`
  refits all of them on each fold's training half;
* LightGBM's early stopping watches the *inner validation fold*, never the
  held-out test rows;
* the test rows are touched exactly once, at the end, by `predict_proba`.
"""
from __future__ import annotations

import random

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split

from features import TARGET, engineer
from pipeline import SEED, build_model

N_FOLDS = 5


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    return engineer(pd.read_csv(csv_path))


def split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])
    return train_test_split(features, labels, test_size=0.2,
                            stratify=labels, random_state=SEED)


def cross_validate_folds(train_x: pd.DataFrame, train_y: pd.Series):
    folds = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    scores = []
    for fold_train, fold_valid in folds.split(train_x, train_y):
        inner_train_x = train_x.iloc[fold_train]
        inner_train_y = train_y.iloc[fold_train]
        inner_valid_x = train_x.iloc[fold_valid]
        inner_valid_y = train_y.iloc[fold_valid]

        booster = lgb.LGBMClassifier(n_estimators=2000, learning_rate=0.03,
                                     num_leaves=63, random_state=SEED)
        model = build_model(booster)
        model.fit(inner_train_x, inner_train_y,
                  clf__eval_set=[(inner_valid_x, inner_valid_y)],
                  clf__eval_metric="auc",
                  clf__callbacks=[lgb.early_stopping(100, verbose=False)])
        fold_scores = model.predict_proba(inner_valid_x)[:, 1]
        scores.append(roc_auc_score(inner_valid_y, fold_scores))
    return float(np.mean(scores))


def fit_final(train_x: pd.DataFrame, train_y: pd.Series):
    booster = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03,
                                 num_leaves=63, random_state=SEED)
    model = build_model(booster)
    model.fit(train_x, train_y)
    return model


def evaluate(model, test_x: pd.DataFrame, test_y: pd.Series) -> dict:
    test_scores = model.predict_proba(test_x)[:, 1]
    return {
        "roc_auc": roc_auc_score(test_y, test_scores),
        "average_precision": average_precision_score(test_y, test_scores),
    }


def main(csv_path: str = "data/churn.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_x, test_x, train_y, test_y = split(frame)
    cv_auc = cross_validate_folds(train_x, train_y)
    model = fit_final(train_x, train_y)
    report = evaluate(model, test_x, test_y)
    report["cv_roc_auc"] = cv_auc
    return report


if __name__ == "__main__":
    print(main())
