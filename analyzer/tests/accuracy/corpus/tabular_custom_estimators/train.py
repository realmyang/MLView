"""Tune the pipeline with GridSearchCV, then score it once on the holdout."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split

from pipeline import SEED, build, search_space

TARGET = "subscribed"


def load(csv_path: str) -> pd.DataFrame:
    return pd.read_csv(csv_path)


def split(frame: pd.DataFrame):
    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])
    return train_test_split(features, labels, test_size=0.25, stratify=labels,
                            random_state=SEED)


def tune(train_x, train_y) -> GridSearchCV:
    folds = StratifiedKFold(n_splits=4, shuffle=True, random_state=SEED)
    search = GridSearchCV(build(), search_space(), cv=folds, scoring="roc_auc",
                          n_jobs=-1, refit=True)
    search.fit(train_x, train_y)
    return search


def main(csv_path: str = "data/subscribers.csv") -> dict:
    np.random.seed(SEED)
    frame = load(csv_path)
    train_x, test_x, train_y, test_y = split(frame)

    search = tune(train_x, train_y)
    probabilities = search.predict_proba(test_x)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)

    return {
        "best_params": search.best_params_,
        "cv_auc": float(search.best_score_),
        "holdout_auc": float(roc_auc_score(test_y, probabilities)),
        "report": classification_report(test_y, predictions, output_dict=True),
    }


if __name__ == "__main__":
    print(main())
