# MLVIEW-EXPECT-NONE: MLV106
"""PUB-06. The trap: an order-preserving splitter on obviously temporal data.

`TimeSeriesSplit` is *the* order-preserving cross-validator, and MLV106 told a
scikit-learn example that `ts_cv.split()` "shuffles rows that look like a time
series" and offered "use TimeSeriesSplit(n_splits=...)" as the fix - advice to
do what the code already does. `KFold(shuffle=False)` (the default) and
`GroupKFold` are the same argument. The genuinely random `train_test_split`
below passes `shuffle=False`, so it is correct too.
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold, KFold, TimeSeriesSplit, train_test_split

SEED = 0


def prepare(path: str):
    np.random.seed(SEED)
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["lag_1h"] = frame["count"].shift(1)
    frame["lag_2h"] = frame["count"].shift(2)
    frame["rolled"] = frame["count"].rolling(24).mean()
    features = frame[["lag_1h", "lag_2h", "rolled"]].to_numpy()
    target = frame["count"].to_numpy()
    groups = frame["station_id"].to_numpy()
    return features, target, groups


def chronological_splits(features, target, groups):
    x_train, x_test, y_train, y_test = train_test_split(
        features, target, test_size=0.2, shuffle=False)

    ts_cv = TimeSeriesSplit(n_splits=3, gap=48)
    windows = list(ts_cv.split(features, target))

    ordered_kfold = KFold(n_splits=5)
    blocks = list(ordered_kfold.split(features, target))

    by_station = GroupKFold(n_splits=4)
    stations = list(by_station.split(features, target, groups))
    return x_train, x_test, y_train, y_test, windows, blocks, stations
