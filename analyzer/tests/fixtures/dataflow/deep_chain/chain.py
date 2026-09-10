"""DATAFLOW-IP probe: the hop cap, and the note that says it was reached.

The feature matrix is handed through four objects before anything is fitted on
it. `DEFAULT_MAX_HOPS` is 3, so the chain runs out one object short of the fit
site - and the point of this fixture is that MLView **says so** rather than
going quiet: a truncated chain that reports nothing is indistinguishable from a
value that never carried a tag, and "I could not check" must never look like "I
checked and it is fine".

# MLVIEW-EXPECT-NONE: MLV101, MLV102
"""
from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

COLUMNS = ["age", "income", "tenure"]


class StageOne:
    def __init__(self, rows):
        self.rows = rows

    def forward(self):
        return StageTwo(self.rows)


class StageTwo:
    def __init__(self, rows):
        self.rows = rows

    def forward(self):
        return StageThree(self.rows)


class StageThree:
    def __init__(self, rows):
        self.rows = rows

    def forward(self):
        return StageFour(self.rows)


class StageFour:
    def __init__(self, rows):
        self.rows = rows

    def prepare(self):
        scaler = StandardScaler()
        scaled = scaler.fit_transform(self.rows)
        return train_test_split(scaled, test_size=0.2, random_state=0)


def main(csv_path: str = "data/churn.csv"):
    frame = pd.read_csv(csv_path)
    features = frame[COLUMNS].to_numpy()
    return StageOne(features).forward().forward().forward().prepare()


if __name__ == "__main__":
    main()
