"""Churn on a table where one account contributes many rows, done correctly.

The thing this file is careful about is the *group*: every row of one
`account_id` must land on the same side of every cut, or the model memorises
the account instead of learning churn.

* the holdout is carved with `GroupShuffleSplit`, so no account straddles it;
* the inner folds come from `StratifiedGroupKFold`, which keeps the class
  balance *and* the account boundary;
* the target encoder is fitted inside each fold, on that fold's training rows
  only, through a `Pipeline` - so no fold ever sees its own validation means;
* CatBoost's early stopping watches the inner validation `Pool`, never the
  held-out test rows;
* the test rows reach exactly one call, `predict_proba`, at the very end.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit, StratifiedGroupKFold
from sklearn.pipeline import Pipeline

from encoders import TargetEncoder
from features import CATEGORICAL, GROUP, TARGET, engineer, split_frame

SEED = 17
N_FOLDS = 5


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    return engineer(pd.read_csv(csv_path))


def holdout_by_group(features, labels, groups):
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    train_index, test_index = next(splitter.split(features, labels, groups))
    train_x = features.iloc[train_index]
    test_x = features.iloc[test_index]
    train_y = labels.iloc[train_index]
    test_y = labels.iloc[test_index]
    return train_x, test_x, train_y, test_y, groups.iloc[train_index]


def build_encoder() -> Pipeline:
    return Pipeline(steps=[("target_enc", TargetEncoder(CATEGORICAL))])


def build_booster(iterations: int = 2000) -> CatBoostClassifier:
    return CatBoostClassifier(iterations=iterations, learning_rate=0.03,
                              depth=6, loss_function="Logloss",
                              eval_metric="AUC", random_seed=SEED,
                              verbose=False)


def cross_validate_groups(train_x, train_y, train_groups) -> dict:
    folds = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True,
                                 random_state=SEED)
    scores = []
    best_rounds = []
    for fold_train, fold_valid in folds.split(train_x, train_y, train_groups):
        inner_train_x = train_x.iloc[fold_train]
        inner_train_y = train_y.iloc[fold_train]
        inner_valid_x = train_x.iloc[fold_valid]
        inner_valid_y = train_y.iloc[fold_valid]

        encoder = build_encoder()
        encoded_train = encoder.fit_transform(inner_train_x, inner_train_y)
        encoded_valid = encoder.transform(inner_valid_x)

        train_pool = Pool(encoded_train, inner_train_y)
        valid_pool = Pool(encoded_valid, inner_valid_y)

        booster = build_booster()
        booster.fit(train_pool, eval_set=valid_pool,
                    early_stopping_rounds=200, verbose=False)

        fold_scores = booster.predict_proba(valid_pool)[:, 1]
        scores.append(roc_auc_score(inner_valid_y, fold_scores))
        best_rounds.append(int(booster.get_best_iteration() or 1))
    return {"auc": float(np.mean(scores)),
            "rounds": int(np.median(best_rounds))}


def fit_final(train_x, train_y, rounds: int):
    encoder = build_encoder()
    encoded_train = encoder.fit_transform(train_x, train_y)
    booster = build_booster(iterations=max(rounds, 50))
    booster.fit(Pool(encoded_train, train_y), verbose=False)
    return encoder, booster


def evaluate(encoder, booster, test_x, test_y) -> dict:
    encoded_test = encoder.transform(test_x)
    scores = booster.predict_proba(Pool(encoded_test))[:, 1]
    return {
        "roc_auc": float(roc_auc_score(test_y, scores)),
        "average_precision": float(average_precision_score(test_y, scores)),
    }


def main(csv_path: str = "data/accounts.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    features, labels, groups = split_frame(frame)
    train_x, test_x, train_y, test_y, train_groups = holdout_by_group(
        features, labels, groups)

    cv = cross_validate_groups(train_x, train_y, train_groups)
    encoder, booster = fit_final(train_x, train_y, cv["rounds"])
    report = evaluate(encoder, booster, test_x, test_y)
    report["cv_roc_auc"] = cv["auc"]
    report["accounts_held_out"] = int(frame.loc[test_x.index, GROUP].nunique())
    return report


if __name__ == "__main__":
    print(main())
