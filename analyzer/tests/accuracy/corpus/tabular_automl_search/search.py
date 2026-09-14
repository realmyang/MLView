"""A hand-rolled AutoML sweep: one matrix, five estimators, one leaderboard.

Planted defects:

* the scaler and the univariate feature selector are fitted on the whole matrix
  before anything is split, and the selector is the worse of the two - it reads
  the target to choose columns, so the columns themselves are chosen with the
  holdout's labels;
* every `cross_val_score` in the sweep is handed a **bare** estimator over that
  already-transformed matrix, so no fold ever refits either step;
* the final holdout is carved out of the same transformed matrix.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesClassifier, GradientBoostingClassifier,
                              RandomForestClassifier)
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import (StratifiedKFold, cross_val_score,
                                     train_test_split)
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

SEED = 3
TARGET = "converted"
K_BEST = 25


def candidates() -> dict:
    return {
        "logreg": LogisticRegression(max_iter=1000, random_state=SEED),
        "rf": RandomForestClassifier(n_estimators=300, random_state=SEED),
        "et": ExtraTreesClassifier(n_estimators=300, random_state=SEED),
        "gb": GradientBoostingClassifier(random_state=SEED),
        "svc": SVC(probability=True, random_state=SEED),
    }


def build_matrix(csv_path: str):
    frame = pd.read_csv(csv_path)
    labels = frame[TARGET]
    matrix = frame.drop(columns=[TARGET])

    scaler = StandardScaler()
    matrix = scaler.fit_transform(matrix)

    selector = SelectKBest(score_func=f_classif, k=K_BEST)
    matrix = selector.fit_transform(matrix, labels)

    return matrix, labels


def sweep(matrix, labels) -> pd.DataFrame:
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    rows = []
    for name, estimator in candidates().items():
        scores = cross_val_score(estimator, matrix, labels, cv=folds,
                                 scoring="roc_auc")
        rows.append({"model": name, "mean_auc": float(np.mean(scores)),
                     "std_auc": float(np.std(scores))})
    return pd.DataFrame(rows).sort_values("mean_auc", ascending=False)


def refit_best(matrix, labels, name: str):
    train_x, test_x, train_y, test_y = train_test_split(
        matrix, labels, test_size=0.2, stratify=labels, random_state=SEED)
    best = candidates()[name]
    best.fit(train_x, train_y)
    return best, roc_auc_score(test_y, best.predict_proba(test_x)[:, 1])


def main(csv_path: str = "data/leads.csv") -> dict:
    matrix, labels = build_matrix(csv_path)
    leaderboard = sweep(matrix, labels)
    winner = str(leaderboard.iloc[0]["model"])
    _model, holdout_auc = refit_best(matrix, labels, winner)
    return {"leaderboard": leaderboard.to_dict("records"),
            "winner": winner, "holdout_auc": holdout_auc}


if __name__ == "__main__":
    print(main())
