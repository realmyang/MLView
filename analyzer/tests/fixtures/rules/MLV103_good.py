# MLVIEW-EXPECT-NONE: MLV103
"""The trap: the very same PCA + LogisticRegression pair, but assembled into a
Pipeline that is handed to cross_val_score, so the transform is refit per fold.
The stateless FunctionTransformer outside the pipeline is fold-invariant."""
import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer


def main(path: str) -> float:
    np.random.seed(0)
    raw = np.load(path)
    X = raw["features"]
    y = raw["labels"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    logger = FunctionTransformer(np.log1p)
    X_train_log = logger.fit_transform(X_train)

    pipeline = Pipeline([
        ("pca", PCA(n_components=16, random_state=42)),
        ("clf", LogisticRegression(max_iter=200)),
    ])
    scores = cross_val_score(pipeline, X_train_log, y_train, cv=5)
    return float(scores.mean())
