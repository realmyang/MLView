"""Row-wise feature engineering for the churn table.

Nothing here is fitted and nothing here reads the label column: every helper is
a pure function of one row's own values, so it is safe to run before the split.
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
    out["charge_gap"] = out["monthly_charges"] - out["charges_per_month"]
    out["log_total"] = np.log1p(out["total_charges"].clip(lower=0))
    return out


def add_flags(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["is_month_to_month"] = (out["contract"] == "Month-to-month").astype(int)
    out["has_fiber"] = (out["internet_service"] == "Fiber optic").astype(int)
    return out


def engineer(frame: pd.DataFrame) -> pd.DataFrame:
    return add_flags(add_ratios(coerce_numeric(frame)))


def numeric_columns() -> list:
    return RAW_NUMERIC + ["charges_per_month", "charge_gap", "log_total",
                          "is_month_to_month", "has_fiber"]


def categorical_columns() -> list:
    return list(RAW_CATEGORICAL)
