"""Out-of-core click prediction: `partial_fit` over chunks, many passes.

The scaler's running mean and variance are updated on training rows only; the
holdout rows are `transform`ed with whatever state the scaler had at that
moment and are never fed back into it. The model sees the same discipline:
`partial_fit` on the training part of each chunk, `decision_function` on the
holdout part.

Both surfaces a leakage rule usually keys on are absent here - there is no
`fit` call and no `train_test_split` - so the correct behaviour on this file is
silence.
"""
from __future__ import annotations

import random

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from stream import FEATURES, chunks, matrices

SEED = 8
EPOCHS = 4
CLASSES = np.array([0, 1])


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def build_model() -> SGDClassifier:
    return SGDClassifier(loss="log_loss", penalty="l2", alpha=1e-6,
                         learning_rate="optimal", random_state=SEED)


def run_epoch(model, scaler, csv_path: str) -> dict:
    holdout_scores = []
    holdout_labels = []
    for train_part, holdout_part in chunks(csv_path):
        train_x, train_y = matrices(train_part)
        scaler.partial_fit(train_x)
        model.partial_fit(scaler.transform(train_x), train_y, classes=CLASSES)

        holdout_x, holdout_y = matrices(holdout_part)
        if len(holdout_y):
            scores = model.predict_proba(scaler.transform(holdout_x))[:, 1]
            holdout_scores.append(scores)
            holdout_labels.append(holdout_y)

    scores = np.concatenate(holdout_scores)
    labels = np.concatenate(holdout_labels)
    return {"roc_auc": float(roc_auc_score(labels, scores)),
            "log_loss": float(log_loss(labels, scores))}


def main(csv_path: str = "data/clicks.csv") -> dict:
    seed_everything()
    model = build_model()
    scaler = StandardScaler()

    history = []
    for epoch in range(EPOCHS):
        metrics = run_epoch(model, scaler, csv_path)
        metrics["epoch"] = epoch
        history.append(metrics)
        print("epoch %d auc %.4f" % (epoch, metrics["roc_auc"]))

    final = history[-1]
    final["features"] = len(FEATURES)
    return final


if __name__ == "__main__":
    print(main())
