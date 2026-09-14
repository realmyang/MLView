"""The base learners and the stack, each declared as a pipeline.

Every base learner carries its own preprocessing, because the linear model
needs scaled inputs and the trees do not, and because a stack that shares one
preprocessor across its members refits nothing per fold.

Nothing here is fitted. These are constructors.
"""
from __future__ import annotations

from sklearn.ensemble import (ExtraTreesClassifier, RandomForestClassifier,
                              StackingClassifier)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 2024


def linear_member() -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(C=0.5, max_iter=4000, random_state=SEED),
    )


def neighbour_member() -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        KNeighborsClassifier(n_neighbors=35, weights="distance"),
    )


def forest_member() -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestClassifier(n_estimators=500, min_samples_leaf=3,
                               n_jobs=-1, random_state=SEED),
    )


def extra_trees_member() -> Pipeline:
    return make_pipeline(
        SimpleImputer(strategy="median"),
        ExtraTreesClassifier(n_estimators=500, min_samples_leaf=3,
                             n_jobs=-1, random_state=SEED),
    )


def base_learners() -> list:
    return [
        ("linear", linear_member()),
        ("knn", neighbour_member()),
        ("forest", forest_member()),
        ("extra", extra_trees_member()),
    ]


def build_stack(folds) -> StackingClassifier:
    """`cv=folds` is the whole point: sklearn builds the meta features
    out-of-fold, so the meta learner never sees a base prediction made on a
    row the base learner was fitted on."""
    return StackingClassifier(
        estimators=base_learners(),
        final_estimator=LogisticRegression(C=1.0, max_iter=2000,
                                           random_state=SEED),
        cv=folds,
        stack_method="predict_proba",
        passthrough=False,
        n_jobs=None,
    )
