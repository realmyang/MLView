"""A scikit-learn baseline over the same pre-extracted features.

Planted here: MLV101 (the scaler is fitted on the whole matrix before the
split), MLV602 (train_test_split has no random_state) and MLV103 (PCA is
fitted once, outside the folds, and a bare estimator is cross-validated).
"""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler

from config import CV_FOLDS, FEATURE_PATH, PCA_COMPONENTS, TEST_FRACTION


def baseline(path: str = FEATURE_PATH):
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=TEST_FRACTION)

    pca = PCA(n_components=PCA_COMPONENTS)
    X_train_pca = pca.fit_transform(X_train)
    X_test_pca = pca.transform(X_test)

    clf = LogisticRegression(max_iter=200)
    scores = cross_val_score(clf, X_train_pca, y_train, cv=CV_FOLDS)
    clf.fit(X_train_pca, y_train)
    holdout = accuracy_score(y_test, clf.predict(X_test_pca))
    return float(scores.mean()), float(holdout)
