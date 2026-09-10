"""The caller that hands the held-out half to `Holder` (see holder.py)."""
import pandas as pd
from sklearn.model_selection import train_test_split

from holder import Holder

COLUMNS = ["a", "b"]


def main():
    frame = pd.read_csv("d.csv")
    features = frame[COLUMNS].to_numpy()
    labels = frame["y"].to_numpy()
    X_train, X_test, y_train, y_test = train_test_split(
        features, labels, random_state=0)
    return Holder(X_test, y_test).build()
