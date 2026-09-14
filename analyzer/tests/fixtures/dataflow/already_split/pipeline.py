"""DATAFLOW-IP negative probe: a helper that legitimately gets training rows.

`fit_on_training_rows` fits a scaler on whatever it is handed - and every call
site hands it the **training half** of a split that already happened. That is
the textbook-correct order, and a rule that fires here would be exactly the
high-severity false positive the roadmap's conditions of approval exist to
prevent.

The interprocedural summary is what makes the silence *earned* rather than
accidental: the parameter carries TRAIN_SPLIT because the call site says so, so
MLV101's `if ref.has("TRAIN_SPLIT"): continue` guard is reached with real
information instead of no information at all.

# MLVIEW-EXPECT-NONE: MLV101, MLV102, MLV103
"""
from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

COLUMNS = ["age", "income", "tenure"]
TARGET = "churned"


def fit_on_training_rows(train_x):
    """Correct: the caller has already split, and this only sees train rows."""
    scaler = StandardScaler()
    return scaler, scaler.fit_transform(train_x)


def main(csv_path: str = "data/churn.csv"):
    frame = pd.read_csv(csv_path)
    features = frame[COLUMNS].to_numpy()
    labels = frame[TARGET].to_numpy()

    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=0.2, random_state=0)

    scaler, scaled_train = fit_on_training_rows(train_x)
    scaled_test = scaler.transform(test_x)

    model = LogisticRegression(max_iter=500, random_state=0)
    model.fit(scaled_train, train_y)
    return model.score(scaled_test, test_y)


if __name__ == "__main__":
    print(main())
