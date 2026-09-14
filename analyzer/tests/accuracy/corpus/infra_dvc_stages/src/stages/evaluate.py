"""DVC stage 3 — score the holdout and write the metrics file DVC tracks.

Nothing is fitted here; the model and the holdout both come off disk. The three
metrics are regression metrics fed continuous predictions, which is what they
take, so no MLV3xx rule has anything to say about this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (mean_absolute_error,
                             mean_absolute_percentage_error,
                             mean_squared_error)

from .prepare import load_params


def compute(y_true, y_pred, wanted) -> dict:
    available = {
        "mae": lambda: float(mean_absolute_error(y_true, y_pred)),
        "rmse": lambda: float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mape": lambda: float(mean_absolute_percentage_error(y_true, y_pred)),
    }
    return {name: available[name]() for name in wanted if name in available}


def main() -> None:
    params = load_params()
    base = params["base"]
    target = params["prepare"]["target_column"]

    model = joblib.load(base["model_path"])
    holdout = pd.read_parquet("data/interim/holdout.parquet")
    y_true = holdout[target]
    x_hold = holdout.drop(columns=[target])

    predictions = model.predict(x_hold)
    metrics = compute(y_true, predictions, params["evaluate"]["metrics"])

    out = Path(base["metrics_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2))
    print(metrics)


if __name__ == "__main__":
    main()
