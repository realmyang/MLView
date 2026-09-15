"""Positive control for ROB-10: the defect MLV101 actually exists for.

A stateful `sklearn.preprocessing` transformer is fitted on the whole matrix and
only then split, so the scaler's mean and variance carry the test rows. MLView
reports MLV101 high here and must keep doing so - whatever guard fixes ROB-10
must not cost this finding.
"""
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def leaky():
    X, y = make_classification(n_samples=200, random_state=0)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    return train_test_split(Xs, y, random_state=0)
