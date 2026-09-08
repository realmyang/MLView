"""Metric callback handed to the Trainer."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    probabilities = np.exp(logits) / np.exp(logits).sum(axis=-1, keepdims=True)
    predictions = logits.argmax(axis=-1)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "f1": f1_score(labels, predictions, average="macro"),
        "auc": roc_auc_score(labels, probabilities[:, 1]),
    }
