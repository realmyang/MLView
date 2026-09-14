"""scikit-learn's own `test_grid_search_correct_score_results`, reduced.

The real file is `sklearn/model_selection/tests/test_search.py`; on the pinned
public-corpus checkout MLView reports this shape as `MLV101` high at lines
1585, 1648, 1664 and in six other scikit-learn test modules.

The test fits a `GridSearchCV` on all of `X` - that *is* the object under test -
and then walks the same folds by hand with `StratifiedKFold.split` to check that
the recorded `split%d_test_score` values match. There is no train/test boundary
in this function to violate, and `GridSearchCV.fit` is not preprocessing.
"""
from sklearn.datasets import make_blobs
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.svm import LinearSVC


def check_scores():
    clf = LinearSVC(random_state=0)
    X, y = make_blobs(random_state=0, centers=2)
    grid = GridSearchCV(clf, {"C": [0.1, 1.0]}, cv=3)
    grid.fit(X, y)
    cv = StratifiedKFold(n_splits=3)
    folds = []
    for train, test in cv.split(X, y):
        clf.fit(X[train], y[train])
        folds.append(clf.score(X[test], y[test]))
    return grid, folds
