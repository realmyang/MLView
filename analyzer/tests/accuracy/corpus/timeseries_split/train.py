"""Walk-forward evaluation of a gradient-boosted forecaster.

Planted defects: the fold loop re-fits a scaler on the test fold, and the
cross-validated baseline scores an already-transformed matrix. No seed is set.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import StandardScaler

from features import build_matrix

N_SPLITS = 5


def walk_forward(csv_path: str = "data/demand.csv"):
    features, target, _, _ = build_matrix(csv_path)
    splitter = TimeSeriesSplit(n_splits=N_SPLITS)

    errors = []
    for train_idx, test_idx in splitter.split(features):
        fold_scaler = StandardScaler()
        test_features = fold_scaler.fit_transform(features[test_idx])

        model = HistGradientBoostingRegressor(max_iter=300)
        model.fit(features[train_idx], target[train_idx])
        errors.append(mean_absolute_error(target[test_idx],
                                          model.predict(test_features)))
    return float(np.mean(errors))


def baseline(csv_path: str = "data/demand.csv"):
    features, target, _, _ = build_matrix(csv_path)
    return cross_val_score(HistGradientBoostingRegressor(), features, target,
                           cv=TimeSeriesSplit(n_splits=N_SPLITS))


if __name__ == "__main__":
    print(walk_forward(), baseline())
