# MLVIEW-EXPECT-NONE: MLV101, MLV102
"""PUB-03 / PUB-04. The trap: one module scope, two unrelated sections.

`_split_consuming` matched the fit's argument to the split's by dotted NAME, so
the `X` of the first section and the `X` of the second - two different arrays
that merely share a name, which is what every sphinx-gallery script and every
notebook looks like - were joined into a high / `certain` leak.

The companion PUB-04 case - `LabelEncoder().fit(frame["label"])`, a vocabulary
encoder on the target - is *not* here, because FP-note (c) de-rates it to
medium x0.6 rather than silencing it; `test_hardening_round1.py` asserts that
grading directly.
"""
import numpy as np
from sklearn.datasets import make_regression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Lasso
from sklearn.model_selection import train_test_split


def two_independent_sections():
    rng = np.random.RandomState(0)
    X = rng.randn(500, 2)
    y = 5 * X[:, 0]
    gbdt = HistGradientBoostingRegressor(random_state=0).fit(X, y)

    X, y = make_regression(n_samples=1000, n_features=20, random_state=0)
    X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=0)
    return gbdt, Lasso(random_state=0).fit(X_train, y_train), X_test, y_test
