# MLVIEW-EXPECT-NONE: MLV106
"""The trap: the same temporal signals and the same train_test_split call, with
shuffle=False - which is exactly how you take a chronological cut with sklearn.
A rule keying on the split plus the date evidence alone would fire here."""
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split

LAGS = (1, 24, 168)
TARGET = "demand"


def build_frame(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp")
    for lag in LAGS:
        frame["lag_%d" % lag] = frame[TARGET].shift(lag)
    return frame.dropna()


def fit(csv_path: str = "data/demand.csv"):
    frame = build_frame(csv_path)
    columns = ["lag_%d" % lag for lag in LAGS]
    train_x, test_x, train_y, test_y = train_test_split(
        frame[columns], frame[TARGET], test_size=0.2, shuffle=False)
    model = HistGradientBoostingRegressor(random_state=0)
    model.fit(train_x, train_y)
    return model, test_x, test_y
