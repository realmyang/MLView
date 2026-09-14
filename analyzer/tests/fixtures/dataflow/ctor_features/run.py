"""The construction site the tag enters through: `ProbeDataModule(X, y)`."""
from __future__ import annotations

import pandas as pd

from datamodule import ProbeDataModule

COLUMNS = ["age", "income", "tenure"]


def main(csv_path: str = "data/churn.csv"):
    frame = pd.read_csv(csv_path)
    X = frame[COLUMNS].to_numpy()
    y = frame["churned"].to_numpy()
    return ProbeDataModule(X, y)


if __name__ == "__main__":
    main()
