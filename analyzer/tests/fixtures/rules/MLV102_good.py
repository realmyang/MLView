# MLVIEW-EXPECT-NONE: MLV102
"""The trap: a stateless FunctionTransformer *is* fit_transform-ed on the test
split (which is harmless, it learns nothing), while the stateful scaler is
fitted on train and only transform-ed on test."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import FunctionTransformer, StandardScaler


def main(path: str) -> float:
    np.random.seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    logger = FunctionTransformer(np.log1p)
    X_train_log = logger.fit_transform(X_train)
    X_test_log = logger.fit_transform(X_test)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train_log)
    X_test_scaled = scaler.transform(X_test_log)

    clf = LogisticRegression(max_iter=200)
    clf.fit(X_train_scaled, y_train)
    return accuracy_score(y_test, clf.predict(X_test_scaled))
