# MLVIEW-EXPECT: MLV306 confidence>=0.6 severity=low
"""R4: a ranking metric fed a class decision that was taken by argmax.

MLV306 used to judge only `predict()`. A hard label is a hard label however it
was produced, and `probs.argmax(axis=1)` is the commoner spelling in a torch
program - the AUC it produces is balanced accuracy wearing an AUC label either
way.
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score


def evaluate(model: RandomForestClassifier, features, labels) -> float:
    probs = model.predict_proba(features)
    hard = probs.argmax(axis=1)
    return roc_auc_score(labels, hard)
