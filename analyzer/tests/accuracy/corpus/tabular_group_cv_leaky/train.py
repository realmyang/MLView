"""The same churn table, and every held-out guarantee quietly broken.

Planted defects, in the order they appear:

* two features are group means of the label column (`prep.engineer`);
* the target encoder is fitted on the whole frame, before any split exists, so
  every category mean carries the held-out rows;
* the frequency encoder is then re-fitted on the test half and used to
  transform it;
* the split is a plain `train_test_split` with no `random_state=` and nothing
  seeds `random` or numpy;
* it is also row-wise, so the same `account_id` lands on both sides of the cut;
* `KFold(shuffle=True)` repeats that mistake for the inner folds and is handed
  a bare booster over a matrix that was already encoded outside the loop;
* CatBoost's early stopping watches the *test* pool, which is model selection
  on the data the final number is reported from;
* the reported AUC is computed from hard labels and the reported accuracy from
  a probability column.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split

from encoders import FrequencyEncoder, TargetEncoder
from prep import CATEGORICAL, TARGET, engineer, feature_columns


def prepare(csv_path: str):
    frame = engineer(pd.read_csv(csv_path))

    labels = frame[TARGET]
    features = frame[feature_columns()]

    encoder = TargetEncoder(CATEGORICAL)
    features = encoder.fit_transform(features, labels)

    counter = FrequencyEncoder(["plan"])
    features = counter.fit_transform(features)

    train_x, test_x, train_y, test_y = train_test_split(features, labels,
                                                        test_size=0.2)
    return train_x, test_x, train_y, test_y, features, labels, counter


def refit_on_holdout(counter, test_x):
    return counter.fit_transform(test_x)


def fit_with_early_stopping(train_x, train_y, test_x, test_y):
    booster = CatBoostClassifier(iterations=5000, learning_rate=0.02, depth=8,
                                 eval_metric="AUC", verbose=False)
    booster.fit(Pool(train_x, train_y),
                eval_set=Pool(test_x, test_y),
                early_stopping_rounds=200,
                verbose=False)
    return booster


def quick_baseline(features, labels):
    folds = KFold(n_splits=5, shuffle=True)
    return cross_val_score(CatBoostClassifier(iterations=200, verbose=False),
                           features, labels, cv=folds, scoring="roc_auc")


def main(csv_path: str = "data/accounts.csv") -> dict:
    train_x, test_x, train_y, test_y, features, labels, counter = prepare(csv_path)

    test_x = refit_on_holdout(counter, test_x)
    booster = fit_with_early_stopping(train_x, train_y, test_x, test_y)

    test_pool = Pool(test_x)
    probabilities = booster.predict_proba(test_pool)[:, 1]
    hard_labels = booster.predict(test_pool)

    baseline = quick_baseline(features, labels)
    return {
        "roc_auc": float(roc_auc_score(test_y, hard_labels)),
        "accuracy": float(accuracy_score(test_y, probabilities)),
        "cv_roc_auc": float(np.mean(baseline)),
    }


if __name__ == "__main__":
    print(main())
