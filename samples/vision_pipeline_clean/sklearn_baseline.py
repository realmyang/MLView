"""A scikit-learn baseline over the same features - corrected twin.

Fix  1 (MLV101): the split happens first; the scaler is fitted on train only.
Fix 14 (MLV602): train_test_split pins random_state.
Fix  6 (MLV103): the transform and the estimator go into a Pipeline, so both
                 are refit inside every cross-validation fold.
"""

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import CV_FOLDS, FEATURE_PATH, PCA_COMPONENTS, SEED, TEST_FRACTION


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("pca", PCA(n_components=PCA_COMPONENTS, random_state=SEED)),
        ("clf", LogisticRegression(max_iter=200)),
    ])


def baseline(path: str = FEATURE_PATH):
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_FRACTION, random_state=SEED)

    pipeline = build_pipeline()
    scores = cross_val_score(pipeline, X_train, y_train, cv=CV_FOLDS)
    pipeline.fit(X_train, y_train)
    holdout = accuracy_score(y_test, pipeline.predict(X_test))
    return float(scores.mean()), float(holdout)
