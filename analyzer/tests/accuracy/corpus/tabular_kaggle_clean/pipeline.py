"""The estimator, assembled so that every fitted step lives inside the Pipeline.

The imputer, the scaler and the one-hot encoder are declared here and fitted
nowhere: `Pipeline.fit` is the only thing that ever fits them, which is what
keeps them refit per fold.
"""
from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from features import categorical_columns, numeric_columns

SEED = 20240917


def build_preprocessor() -> ColumnTransformer:
    numeric = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=20)),
    ])
    return ColumnTransformer(
        transformers=[
            ("num", numeric, numeric_columns()),
            ("cat", categorical, categorical_columns()),
        ],
        remainder="drop",
    )


def build_model(estimator) -> Pipeline:
    return Pipeline(steps=[
        ("prep", build_preprocessor()),
        ("clf", estimator),
    ])
