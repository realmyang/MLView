"""Active learning with a pool-based acquisition loop - the defective version.

Round 1's `adv_advanced_clean/curriculum.py` is the *legitimate* re-split: a
curriculum that re-partitions its own training rows every round is not a leak,
and MLView must not call it one. This file is the twin that really does leak,
and the distinction is exactly one line: the acquisition function scores the
**test** pool and the rows it selects are moved into the labelled training set,
so by the last round the model has been fitted on most of its own test set.

Eight defects; the leak itself is the one that matters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

ROUNDS = 8
BATCH = 200


def load_frame(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def prepare(frame: pd.DataFrame):
    features = frame.drop(columns=["target"])
    target = frame["target"]
    # DEFECT: the scaler is fitted on every row, including the rows that become
    # the test split two lines below, so the test mean and variance are part of
    # the transform the model is trained through.
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    # DEFECT: no random_state, so the pool and the test set move between runs.
    x_train, x_test, y_train, y_test = train_test_split(scaled, target,
                                                        test_size=0.3)
    return x_train, x_test, y_train, y_test, scaler


def acquisition_scores(model, pool):
    """Least-confidence acquisition over whatever pool it is handed."""
    probabilities = model.predict_proba(pool)
    return 1.0 - probabilities.max(axis=1)


def active_round(model, x_labelled, y_labelled, x_pool, y_pool):
    """One acquisition round.

    DEFECT: the pool handed in by the caller is the TEST split, so the `BATCH`
    rows this returns are held-out rows promoted into the training set.
    """
    model.fit(x_labelled, y_labelled)
    scores = acquisition_scores(model, x_pool)
    chosen = np.argsort(scores)[-BATCH:]
    x_labelled = np.concatenate([x_labelled, x_pool[chosen]])
    y_labelled = np.concatenate([y_labelled, np.asarray(y_pool)[chosen]])
    return x_labelled, y_labelled, chosen


def main(path: str) -> None:
    # DEFECT: nothing seeds numpy or sklearn anywhere in this project.
    frame = load_frame(path)
    x_train, x_test, y_train, y_test, scaler = prepare(frame)

    model = RandomForestClassifier(n_estimators=200)
    for round_index in range(ROUNDS):
        # DEFECT: the acquisition pool IS the test split.
        x_train, y_train, chosen = active_round(model, x_train, y_train,
                                                x_test, y_test)
        # DEFECT: the transform is re-fitted on the test split every round.
        scaler.fit(x_test)
        # DEFECT: cross_val_score is given the bare estimator after a
        # fit_transform on the same matrix, so the scaling is not refit per
        # fold and the cross-validated score is optimistic.
        folds = cross_val_score(model, x_train, y_train, cv=5)
        print("round %d cv %.4f" % (round_index, float(np.mean(folds))))

    model.fit(x_train, y_train)
    # DEFECT: roc_auc_score is fed hard predicted labels rather than scores.
    predictions = model.predict(x_test)
    print("test auc %.4f" % roc_auc_score(y_test, predictions))
