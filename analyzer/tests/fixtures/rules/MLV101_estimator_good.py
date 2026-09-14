# MLVIEW-EXPECT-NONE: MLV101, MLV102, MLV103
"""ROB-10 / PUB-02. The trap: an *estimator* fit beside a cross-validator.

`sklearn.base.BaseEstimator.fit` carries the role `FIT`, so every estimator fit
was an MLV101 candidate - and the rule's second half accepts a splitter's
`.split()` as "the train/test split". `GridSearchCV` refits inside every fold
and `final` is the deployed refit; neither is preprocessing, and neither block
contains a transformer at all. On a shallow clone of scikit-learn this shape
was 13 of the 13 high-severity findings MLView produced on its own source.
"""
import numpy as np
from sklearn.datasets import make_moons
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV, KFold, RepeatedStratifiedKFold
from sklearn.svm import SVC


def tuned_search():
    features, labels = make_moons(noise=0.35, random_state=1, n_samples=100)
    cv = RepeatedStratifiedKFold(n_splits=10, n_repeats=10, random_state=0)
    search = GridSearchCV(estimator=SVC(random_state=0),
                          param_grid=[{"kernel": ["rbf"]}], cv=cv)
    search.fit(features, labels)
    return search, len(next(iter(cv.split(features, labels)))[0])


def refit_then_cross_validate(features, labels):
    splitter = KFold(n_splits=5, shuffle=True, random_state=0)
    scores = []
    for train_idx, test_idx in splitter.split(features, labels):
        fold = RandomForestClassifier(random_state=0)
        fold.fit(features[train_idx], labels[train_idx])
        scores.append(fold.score(features[test_idx], labels[test_idx]))
    final = RandomForestClassifier(random_state=0)
    final.fit(features, labels)
    return final, float(np.mean(scores))
