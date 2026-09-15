# MLVIEW-EXPECT-NONE: MLV101, MLV102
"""PUB-15. The PUB-03 trap again, bound the way scikit-learn actually binds.

`MLV101_sections_good.py` is the same shape with an *estimator* fit, so PUB-02's
`_is_transformer_fit` silences it before the rebinding guard is ever consulted -
which is why this half stayed broken for a round. Here the fit is a
`SequentialFeatureSelector`, a real transformer, so `_rebound_between` is the
only thing standing between two unrelated sections and a high / `certain` leak.

The rebinding is `X, y = ...`, one `ast.Tuple` target. `AssignRecord.targets` is
the raw `stmt.targets`, and `dotted_text` of a tuple is empty, so the guard
PUB-03 wrote for `X = ...` could not see the single commonest spelling in the
ecosystem. Measured on scikit-learn's own
`examples/release_highlights/plot_release_highlights_0_24_0.py:153`, where the
fit is on iris and the split twenty-seven lines later is on covtype.

Nothing here is fitted before a split of its own data: the iris section has no
split at all, and the covtype section splits before it fits.
"""
from sklearn.datasets import fetch_covtype, load_iris
from sklearn.feature_selection import SequentialFeatureSelector
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier


def two_independent_sections():
    X, y = load_iris(return_X_y=True, as_frame=True)
    knn = KNeighborsClassifier(n_neighbors=3)
    sfs = SequentialFeatureSelector(knn, n_features_to_select=2)
    sfs.fit(X, y)

    X, y = fetch_covtype(return_X_y=True)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, train_size=5000, test_size=10000, random_state=42
    )
    model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
    return sfs, model, X_test, y_test
