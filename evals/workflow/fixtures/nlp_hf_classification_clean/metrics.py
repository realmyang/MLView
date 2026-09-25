"""`compute_metrics`, written the way it should be.

The logits are turned into class predictions once, at the top, and the ranking
metric is the only thing that still sees a continuous score.
"""
from __future__ import annotations

import numpy as np
from scipy.special import softmax
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    probabilities = softmax(logits, axis=-1)
    return {
        "accuracy": accuracy_score(labels, preds),
        "macro_f1": f1_score(labels, preds, average="macro"),
        "auc": roc_auc_score(labels, probabilities, multi_class="ovr"),
    }


def per_class_report(logits, labels):
    preds = np.argmax(logits, axis=-1)
    rows = {}
    for index in range(logits.shape[-1]):
        mask = labels == index
        rows[index] = float((preds[mask] == index).mean())
    return rows
