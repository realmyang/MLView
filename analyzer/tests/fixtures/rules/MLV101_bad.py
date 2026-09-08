# MLVIEW-EXPECT: MLV101 line=17 confidence>=0.6
"""StandardScaler fitted on the full X before train_test_split."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def main(path: str) -> float:
    np.random.seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42)

    clf = LogisticRegression(max_iter=200)
    clf.fit(X_train, y_train)
    return accuracy_score(y_test, clf.predict(X_test))
