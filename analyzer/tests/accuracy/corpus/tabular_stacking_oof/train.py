"""A four-model stack, blended out-of-fold, written correctly.

The blend is built twice on purpose, because both spellings appear in real
competition code and both must stay silent:

* `cross_val_predict` produces the out-of-fold meta features by hand, and the
  meta learner is fitted on those and on nothing else;
* `StackingClassifier(cv=folds)` does the same thing inside one object.

Each base learner is a `Pipeline`, so its imputer and its scaler are refit on
every fold's training half. The held-out rows reach `predict_proba` and
nothing else.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import (StratifiedKFold, cross_val_predict,
                                     train_test_split)

from models import SEED, base_learners, build_stack

TARGET = "responded"
N_FOLDS = 5


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    return frame.dropna(subset=[TARGET])


def split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])
    return train_test_split(features, labels, test_size=0.2,
                            stratify=labels, random_state=SEED)


def out_of_fold_matrix(train_x, train_y, folds):
    """One column per base learner, every entry predicted by a model that was
    fitted without the row it is predicting."""
    columns = []
    for _name, member in base_learners():
        oof = cross_val_predict(member, train_x, train_y, cv=folds,
                                method="predict_proba", n_jobs=None)
        columns.append(oof[:, 1])
    return np.column_stack(columns)


def fit_blend(train_x, train_y, folds):
    meta_features = out_of_fold_matrix(train_x, train_y, folds)
    meta = LogisticRegression(C=1.0, max_iter=2000, random_state=SEED)
    meta.fit(meta_features, train_y)

    fitted_members = []
    for name, member in base_learners():
        member.fit(train_x, train_y)
        fitted_members.append((name, member))
    return meta, fitted_members


def blend_predict(meta, fitted_members, features):
    columns = [member.predict_proba(features)[:, 1]
               for _name, member in fitted_members]
    return meta.predict_proba(np.column_stack(columns))[:, 1]


def main(csv_path: str = "data/marketing.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_x, test_x, train_y, test_y = split(frame)

    folds = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)

    meta, fitted_members = fit_blend(train_x, train_y, folds)
    manual_scores = blend_predict(meta, fitted_members, test_x)

    stack = build_stack(folds)
    stack.fit(train_x, train_y)
    stack_scores = stack.predict_proba(test_x)[:, 1]

    return {
        "manual_blend_auc": float(roc_auc_score(test_y, manual_scores)),
        "stacking_auc": float(roc_auc_score(test_y, stack_scores)),
        "stacking_log_loss": float(log_loss(test_y, stack_scores)),
    }


if __name__ == "__main__":
    print(main())
