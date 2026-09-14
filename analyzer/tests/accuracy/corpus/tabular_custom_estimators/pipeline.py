"""The estimator: custom transformers assembled into a ColumnTransformer.

Every fitted object below is a `Pipeline` step, so `GridSearchCV` refits all of
them on each fold's training half. Nothing in this file calls `.fit` at all.
"""
from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from transformers import (RareCategoryGrouper, WinsorizingTransformer,
                          make_log_transformer)

SEED = 1234
HEAVY_TAILED = ["revenue", "sessions", "page_views"]
NUMERIC = ["age", "tenure_days"]
CATEGORICAL = ["country", "device", "referrer"]


def build() -> Pipeline:
    heavy = Pipeline(steps=[
        ("winsorize", WinsorizingTransformer(lower=0.005, upper=0.995)),
        ("log", make_log_transformer()),
        ("scale", StandardScaler()),
    ])
    numeric = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical = Pipeline(steps=[
        ("group", RareCategoryGrouper(min_count=30)),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocessor = ColumnTransformer(transformers=[
        ("heavy", heavy, HEAVY_TAILED),
        ("num", numeric, NUMERIC),
        ("cat", categorical, CATEGORICAL),
    ])
    return Pipeline(steps=[
        ("prep", preprocessor),
        ("clf", RandomForestClassifier(n_estimators=400, random_state=SEED)),
    ])


def search_space() -> dict:
    return {
        "prep__heavy__winsorize__upper": [0.99, 0.995, 0.999],
        "prep__cat__group__min_count": [10, 30, 100],
        "clf__max_depth": [None, 8, 16],
    }
