"""Feature engineering for the churn table - the defective twin.

`add_target_stats` is the classic Kaggle mistake: a feature whose value is a
group mean of the label column. Every row's own outcome is inside its own
feature, so the validation score is a memory test and the production score is
whatever the base rate happens to be.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RAW_NUMERIC = ["monthly_charges", "total_charges", "tenure_months"]
RAW_CATEGORICAL = ["contract", "payment_method", "internet_service"]
TARGET = "churned"


def coerce_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in RAW_NUMERIC:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def add_ratios(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["charges_per_month"] = out["total_charges"] / out["tenure_months"].clip(lower=1)
    out["log_total"] = np.log1p(out["total_charges"].clip(lower=0))
    return out


def add_target_stats(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["contract_churn_rate"] = out.groupby("contract")[TARGET].transform("mean")
    out["payment_churn_rate"] = out.groupby("payment_method")[TARGET].transform("mean")
    return out


def engineer(frame: pd.DataFrame) -> pd.DataFrame:
    return add_target_stats(add_ratios(coerce_numeric(frame)))


def feature_columns() -> list:
    return RAW_NUMERIC + ["charges_per_month", "log_total",
                          "contract_churn_rate", "payment_churn_rate"]
