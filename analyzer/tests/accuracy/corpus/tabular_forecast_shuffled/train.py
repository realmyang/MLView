"""The same hourly forecast, evaluated with a shuffled split.

Planted defects:

* the holdout is `train_test_split(..., shuffle=True)` on a sorted, parsed
  timestamp series - every test hour has its two neighbouring hours in the
  training set, so the score measures interpolation, not forecasting;
* the scaler is fitted on the whole matrix before that split;
* `KFold(shuffle=True)` does the same thing again inside cross-validation, over
  a matrix that was already scaled outside the loop, with a bare estimator;
* `lags.build` back-fills the warm-up rows, which copies future values
  backwards past the cut.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

from lags import TARGET, build, feature_columns

SEED = 7


def prepare(csv_path: str):
    frame = build(csv_path)
    columns = feature_columns(frame)
    matrix = frame[columns]
    target = frame[TARGET]

    scaler = StandardScaler()
    matrix = scaler.fit_transform(matrix)

    train_x, test_x, train_y, test_y = train_test_split(
        matrix, target, test_size=0.2, shuffle=True, random_state=SEED)
    return train_x, test_x, train_y, test_y, matrix, target


def quick_cv(matrix, target):
    folds = KFold(n_splits=5, shuffle=True, random_state=SEED)
    return cross_val_score(HistGradientBoostingRegressor(random_state=SEED),
                           matrix, target, cv=folds,
                           scoring="neg_mean_absolute_error")


def main(csv_path: str = "data/load.csv") -> dict:
    train_x, test_x, train_y, test_y, matrix, target = prepare(csv_path)

    model = HistGradientBoostingRegressor(max_iter=400, random_state=SEED)
    model.fit(train_x, train_y)
    predictions = model.predict(test_x)

    return {
        "holdout_mae": float(mean_absolute_error(test_y, predictions)),
        "cv_mae": float(-np.mean(quick_cv(matrix, target))),
    }


if __name__ == "__main__":
    print(main())
