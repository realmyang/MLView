# MLVIEW-EXPECT: MLV101 line=19 confidence>=0.6
"""The pandas path: the feature matrix is built with df.drop(columns=[...]),
so the RAW_DATA tag pandas.read_csv seeds has to survive the hop before the
scaler is fitted on the whole frame ahead of the split."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def main(path: str) -> float:
    np.random.seed(0)
    frame = pd.read_csv(path)
    target = frame["churn"]
    features = frame.drop(columns=["churn"]).fillna(0.0)

    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    X_train, X_test, y_train, y_test = train_test_split(
        scaled, target, test_size=0.2, random_state=42)

    clf = LogisticRegression(max_iter=200)
    clf.fit(X_train, y_train)
    return clf.score(X_test, y_test)
