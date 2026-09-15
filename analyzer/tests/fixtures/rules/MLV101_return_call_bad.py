# MLVIEW-EXPECT: MLV101 line=16 severity=high
"""REC-03: the helper returns the fit's value directly instead of binding it.

`return scaler.fit_transform(frame)` is the same program as `matrix =
scaler.fit_transform(frame); return matrix` (that spelling is `MLV101_bad.py`),
and R13 used to read only the second: `dotted_text` reports a call as its
*callee*, so the returned position was never recognised as fed by the fit."""
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def prepare(frame):
    scaler = StandardScaler()
    return scaler.fit_transform(frame)


def main(path: str) -> LogisticRegression:
    frame = pd.read_csv(path)
    y = frame.pop("target")
    X = prepare(frame)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=1)
    return LogisticRegression(max_iter=200).fit(X_train, y_train)
