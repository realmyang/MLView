# MLVIEW-EXPECT: MLV103 line=24 severity=medium
"""REC-03, the R15 half: the helper that builds X returns the fit's value.

`return pca.fit_transform(X)` and `reduced = pca.fit_transform(X); return
reduced` are one program, and `_returned_names` read only the name form -
`dotted_text` of a call is its callee (`pca.fit_transform`), which names no
value at all, so the cross-validated matrix was never traced back to the fit."""
import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score


def reduce_dims(X):
    pca = PCA(n_components=16, random_state=42)
    return pca.fit_transform(X)


def main(path: str) -> float:
    np.random.seed(0)
    raw = np.load(path)
    features = reduce_dims(raw["features"])
    clf = LogisticRegression(max_iter=200)
    scores = cross_val_score(clf, features, raw["labels"], cv=5)
    return float(scores.mean())
