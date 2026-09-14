"""`compute_metrics` for the Trainer — the version people actually write.

`eval_pred` is a `(logits, labels)` pair. Everything below treats the logits as
if they were already class predictions.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    return {
        "accuracy": accuracy_score(labels, logits),
        "macro_f1": f1_score(labels, logits, average="macro"),
        "auc": roc_auc_score(labels, np.asarray(logits), multi_class="ovr"),
    }


def per_class_report(logits, labels):
    preds = np.argmax(logits, axis=-1)
    rows = {}
    for index in range(logits.shape[-1]):
        mask = labels == index
        rows[index] = float((preds[mask] == index).mean())
    return rows
