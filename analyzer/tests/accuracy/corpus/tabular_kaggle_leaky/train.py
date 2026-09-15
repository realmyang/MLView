"""The same churn baseline, written the way it is usually written first.

Planted defects, in the order they appear:

* the ordinal encoder and the median imputer are both fitted on the whole
  frame, before any split exists;
* the split has no `random_state=` and nothing seeds numpy;
* SMOTE is applied to the held-out half, so the test set is half synthetic
  rows interpolated from its own neighbours;
* the scaler is re-fitted on the held-out half and used to transform it;
* early stopping watches the test set, which is model selection on the data the
  final number is reported from;
* `cross_val_score` is handed a bare estimator over a matrix that was already
  scaled outside the loop;
* two features in `prep.py` are group means of the label column.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from prep import RAW_CATEGORICAL, TARGET, engineer, feature_columns


def prepare(csv_path: str):
    frame = engineer(pd.read_csv(csv_path))

    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    frame[RAW_CATEGORICAL] = encoder.fit_transform(frame[RAW_CATEGORICAL])

    labels = frame[TARGET]
    features = frame[feature_columns() + RAW_CATEGORICAL]

    imputer = SimpleImputer(strategy="median")
    features = imputer.fit_transform(features)

    scaler = StandardScaler()
    features = scaler.fit_transform(features)

    train_x, test_x, train_y, test_y = train_test_split(features, labels,
                                                        test_size=0.2)
    return train_x, test_x, train_y, test_y, scaler, features, labels


def balance(test_x, test_y):
    sampler = SMOTE(k_neighbors=5)
    resampled_x, resampled_y = sampler.fit_resample(test_x, test_y)
    return resampled_x, resampled_y


def fit_with_early_stopping(train_x, train_y, test_x, test_y):
    booster = lgb.LGBMClassifier(n_estimators=5000, learning_rate=0.02)
    booster.fit(train_x, train_y,
                eval_set=[(test_x, test_y)],
                eval_metric="auc",
                callbacks=[lgb.early_stopping(200, verbose=False)])
    return booster


def quick_baseline(features, labels):
    return cross_val_score(lgb.LGBMClassifier(n_estimators=200), features,
                           labels, cv=5, scoring="roc_auc")


def main(csv_path: str = "data/churn.csv"):
    train_x, test_x, train_y, test_y, scaler, features, labels = prepare(csv_path)

    test_x = scaler.fit_transform(test_x)
    test_x, test_y = balance(test_x, test_y)

    booster = fit_with_early_stopping(train_x, train_y, test_x, test_y)
    scores = booster.predict_proba(test_x)[:, 1]

    print("cv", float(np.mean(quick_baseline(features, labels))))
    return roc_auc_score(test_y, scores)


if __name__ == "__main__":
    print(main())
