# MLVIEW-EXPECT-NONE: MLV306, MLV305
"""The trap: the ranking metric gets the *scores*, and the class metric gets
the classes, in the same file and off the same two names.

A rule that reads "argmax appears in this function" rather than "argmax
produced this argument" would fire here, and it would be wrong twice.
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score


def evaluate(model: RandomForestClassifier, features, labels):
    probs = model.predict_proba(features)
    hard = probs.argmax(axis=1)
    return (roc_auc_score(labels, probs[:, 1]),
            accuracy_score(labels, hard))
