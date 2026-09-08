# MLVIEW-EXPECT: MLV103 line=22 confidence>=0.6 severity=medium
"""PCA is fitted once, outside the folds, and a bare estimator is cross-validated."""
import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split


def main(path: str) -> float:
    np.random.seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    pca = PCA(n_components=16, random_state=42)
    X_train_pca = pca.fit_transform(X_train)

    clf = LogisticRegression(max_iter=200)
    scores = cross_val_score(clf, X_train_pca, y_train, cv=5)
    return float(scores.mean())
