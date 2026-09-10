"""DATAFLOW-IP negative probe: one helper, two call sites, different tags.

`summarize` is called once with the training half and once with the test half
of the same split. Under a **union** summary its `values` parameter would carry
TRAIN_SPLIT *and* TEST_SPLIT at the same time, MLV102 ("transformer fitted on
validation or test data", severity **high**) would fire inside `summarize`, and
the tool would have invented a defect out of two correct calls.

Under the **intersection** the roadmap makes a condition of approval, the two
sites agree on FEATURES and on nothing else, which is the truth: the helper is
handed feature rows, and which half of the split they came from depends on the
caller. Neither leakage rule fires, and the analyzer keeps its credibility.

# MLVIEW-EXPECT-NONE: MLV101, MLV102, MLV103
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

COLUMNS = ["age", "income", "tenure"]
TARGET = "churned"


def summarize(values):
    """Called from both sides of the split; z-scores whatever it is handed."""
    scaler = StandardScaler()
    return np.round(scaler.fit_transform(values).mean(axis=0), 3)


def main(csv_path: str = "data/churn.csv"):
    frame = pd.read_csv(csv_path)
    features = frame[COLUMNS].to_numpy()
    labels = frame[TARGET].to_numpy()

    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=0.2, random_state=0)

    return summarize(train_x), summarize(test_x)


if __name__ == "__main__":
    print(main())
