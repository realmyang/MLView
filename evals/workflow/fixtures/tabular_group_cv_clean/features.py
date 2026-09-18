"""Row-wise feature engineering for the support-ticket churn table.

Every derived column here is a function of the row it belongs to. Nothing is a
group statistic, nothing reads the label column, and nothing needs a fitted
state - which is what makes it safe to run before the split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "churned"
GROUP = "account_id"
CATEGORICAL = ["plan", "region", "acquisition_channel"]
NUMERIC = [
    "tenure_months",
    "monthly_spend",
    "tickets_opened",
    "tickets_per_month",
    "spend_per_month",
    "log_spend",
]


def engineer(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["tickets_per_month"] = out["tickets_opened"] / out["tenure_months"].clip(lower=1)
    out["spend_per_month"] = out["monthly_spend"] / out["tenure_months"].clip(lower=1)
    out["log_spend"] = np.log1p(out["monthly_spend"].clip(lower=0))
    out[CATEGORICAL] = out[CATEGORICAL].fillna("__missing__")
    return out


def feature_columns() -> list:
    return NUMERIC + CATEGORICAL


def split_frame(frame: pd.DataFrame):
    """Features, labels and the grouping key, in that order."""
    labels = frame[TARGET]
    groups = frame[GROUP]
    features = frame[feature_columns()]
    return features, labels, groups
