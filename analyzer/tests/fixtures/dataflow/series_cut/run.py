"""The construction site: the whole series goes in here."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from experiment import SeriesExperiment

COLUMNS = ["lag_1", "lag_24", "rolling_24"]
TARGET = "demand"


def main(csv_path: str = "data/hourly.csv"):
    frame = pd.read_csv(csv_path)
    features = frame[COLUMNS].to_numpy()
    demand = frame[TARGET].to_numpy()

    experiment = SeriesExperiment(features, demand)
    train_x, test_x, train_y, test_y = experiment.prepare()

    model = Ridge(alpha=1.0, random_state=0)
    model.fit(train_x, train_y)
    return float(np.mean(np.abs(model.predict(test_x) - test_y)))


if __name__ == "__main__":
    print(main())
