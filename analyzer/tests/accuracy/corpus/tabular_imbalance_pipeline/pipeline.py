"""The estimator, assembled so that every fitted step is inside one object.

`imblearn.pipeline.Pipeline` exists because `sklearn.pipeline.Pipeline` refuses
to resample: it calls `transform` on validation rows, and a resampler has no
`transform`. The imblearn version calls `fit_resample` on the training half of
each fold and leaves the validation half alone, which is precisely the
behaviour that makes SMOTE-inside-CV correct and SMOTE-before-CV wrong.

Nothing in this module calls `fit`. Every object here is *declared* as a step
and fitted later, once per fold, by whoever holds the pipeline.
"""
from __future__ import annotations

from imblearn.over_sampling import SMOTENC
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, RobustScaler

SEED = 41

NUMERIC = ["amount", "hour_of_day", "days_since_last_txn", "merchant_risk",
           "amount_to_median_ratio"]
CATEGORICAL = ["merchant_category", "device_type", "country"]


def build_preprocessor() -> ColumnTransformer:
    numeric = ImbPipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", RobustScaler()),
    ])
    categorical = ImbPipeline(steps=[
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return ColumnTransformer(transformers=[
        ("num", numeric, NUMERIC),
        ("cat", categorical, CATEGORICAL),
    ])


def build_estimator(sampling_strategy: float = 0.25) -> ImbPipeline:
    """Preprocess -> resample -> fit, as one object the CV loop can refit."""
    return ImbPipeline(steps=[
        ("prep", build_preprocessor()),
        ("smote", SMOTENC(categorical_features="auto",
                          sampling_strategy=sampling_strategy,
                          k_neighbors=5, random_state=SEED)),
        ("clf", HistGradientBoostingClassifier(max_iter=400,
                                               learning_rate=0.05,
                                               random_state=SEED)),
    ])
