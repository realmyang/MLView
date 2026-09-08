"""The correct answer to MLV101 / MLV103: a Pipeline fitted inside the search.

Every transform is a pipeline step, so it is refit on each fold; every random
source carries an explicit `random_state`.
"""
from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report
from sklearn.model_selection import (GridSearchCV, StratifiedKFold, cross_val_score,
                                     train_test_split)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42


def build_pipeline(numeric, categorical) -> Pipeline:
    preprocess = ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())]), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
    ])
    return Pipeline([
        ("prep", preprocess),
        ("clf", RandomForestClassifier(n_estimators=200, random_state=SEED)),
    ])


def main(path: str, numeric, categorical):
    np.random.seed(SEED)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED, stratify=y)

    pipeline = build_pipeline(numeric, categorical)
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    baseline = cross_val_score(pipeline, X_train, y_train, cv=folds, scoring="f1_macro")

    search = GridSearchCV(
        pipeline,
        {"clf__max_depth": [None, 8, 16]},
        cv=folds,
        scoring="f1_macro",
        n_jobs=1,
    )
    search.fit(X_train, y_train)

    report = classification_report(y_test, search.predict(X_test))
    return float(baseline.mean()), search.best_params_, report
