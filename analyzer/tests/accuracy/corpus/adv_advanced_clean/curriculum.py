"""Active learning with a legitimate re-split every round - correct.

This is the shape a leakage rule is most likely to get wrong. The test set is
cut **once**, before the loop, and is never touched again. Inside the loop the
*labelled pool* grows by one acquisition batch per round, and the train/holdout
split is redrawn **from the pool only** - which is legitimate and is the whole
point of an active-learning curriculum: the pool is a different dataset every
round, so a split computed last round no longer covers it.

Every transformer is fitted inside a `Pipeline`, so the scaler and the selector
are refitted on the training fold of the round and never see the holdout, the
pool's unlabelled half, or the test set.

Nothing here is a defect. In particular MLV101, MLV102, MLV103 and MLV106 must
all stay silent: the repeated `train_test_split` inside the loop is a re-split
of a growing pool, not a leak.
"""

from __future__ import annotations

import random

import numpy as np
from sklearn.datasets import fetch_covtype
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEED = 61
ROUNDS = 10
SEED_LABELS = 500
ACQUIRE = 250


def build_pipeline() -> Pipeline:
    """Scaler, selector and estimator in one object, so `fit` refits all three."""
    return Pipeline([
        ("scale", StandardScaler()),
        ("select", SelectKBest(score_func=f_classif, k=20)),
        ("model", RandomForestClassifier(n_estimators=200, random_state=SEED,
                                         n_jobs=-1)),
    ])


def most_uncertain(pipeline, pool_features, how_many: int):
    """Least-confidence acquisition over the unlabelled pool."""
    probabilities = pipeline.predict_proba(pool_features)
    confidence = probabilities.max(axis=1)
    return np.argsort(confidence)[:how_many]


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)

    data = fetch_covtype()
    features, target = data.data, data.target

    # The test set is cut once, here, and nothing below ever reads it again
    # until the final line.
    pool_features, test_features, pool_target, test_target = train_test_split(
        features, target, test_size=0.2, random_state=SEED, stratify=target)

    labelled = np.zeros(pool_features.shape[0], dtype=bool)
    labelled[np.random.choice(pool_features.shape[0], SEED_LABELS, replace=False)] = True

    history = []
    for round_index in range(ROUNDS):
        # A legitimate re-split: `labelled` grew since the previous round, so
        # the training fold and the holdout fold are redrawn from the larger
        # labelled pool. Both halves are still inside the pool, and the test
        # set took no part in it.
        round_features = pool_features[labelled]
        round_target = pool_target[labelled]
        train_features, holdout_features, train_target, holdout_target = train_test_split(
            round_features, round_target, test_size=0.25,
            random_state=SEED + round_index, stratify=round_target)

        pipeline = build_pipeline()
        pipeline.fit(train_features, train_target)

        holdout_predictions = pipeline.predict(holdout_features)
        holdout_f1 = f1_score(holdout_target, holdout_predictions, average="macro")
        history.append((int(labelled.sum()), float(holdout_f1)))
        print("round %d: %d labels, holdout macro-F1 %.4f"
              % (round_index, labelled.sum(), holdout_f1))

        unlabelled_index = np.flatnonzero(~labelled)
        if unlabelled_index.size == 0:
            break
        chosen = most_uncertain(pipeline, pool_features[unlabelled_index], ACQUIRE)
        labelled[unlabelled_index[chosen]] = True

    # One final fit on everything that was ever labelled, then the test set is
    # read for the first and only time.
    final = build_pipeline()
    final.fit(pool_features[labelled], pool_target[labelled])
    test_predictions = final.predict(test_features)
    print("curriculum finished with %d labels; test accuracy %.4f, macro-F1 %.4f"
          % (labelled.sum(),
             accuracy_score(test_target, test_predictions),
             f1_score(test_target, test_predictions, average="macro")))
    print("holdout history:", history)


if __name__ == "__main__":
    main()
