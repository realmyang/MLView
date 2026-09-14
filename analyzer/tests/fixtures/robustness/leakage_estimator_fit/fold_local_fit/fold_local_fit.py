"""Negative control for ROB-10: every fit happens inside the fold.

MLView is correctly silent on this file today, and must stay silent: it is the
half of the shape that carries no estimator fit outside the loop.
"""
from sklearn.datasets import make_regression
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold


def run():
    X, y = make_regression(n_samples=100, random_state=0)
    kf = KFold(n_splits=4)
    out = []
    for tr, te in kf.split(X, y):
        model = Ridge(alpha=1.0)
        model.fit(X[tr], y[tr])
        out.append(model.predict(X[te]))
    return out
