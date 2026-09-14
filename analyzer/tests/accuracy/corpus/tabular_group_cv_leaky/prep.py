"""Feature engineering for the same churn table, written the usual first way.

Two of the columns built here are group statistics of the label column. They
are the single most effective feature in every offline experiment and the
single reason the model collapses in production: at scoring time the label does
not exist yet, so `region_churn_rate` has to be filled from the training frame,
and every account that was in that frame carries its own answer in it.
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
    "region_churn_rate",
    "plan_churn_rate",
]


def engineer(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["tickets_per_month"] = out["tickets_opened"] / out["tenure_months"].clip(lower=1)
    out["region_churn_rate"] = out.groupby("region")[TARGET].transform("mean")
    out["plan_churn_rate"] = out.groupby("plan")[TARGET].transform("mean")
    out[CATEGORICAL] = out[CATEGORICAL].fillna("__missing__")
    return out


def feature_columns() -> list:
    return NUMERIC + CATEGORICAL
