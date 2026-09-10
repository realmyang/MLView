"""DATAFLOW-IP negative probe: a parameter *merely named* `X`.

The nine-variant probe ladder that motivated DATAFLOW-IP ends here: MLView must
not conclude anything from a name. `fit_scaler` is a library helper nothing in
this workspace calls, so there is no call site to intersect, no argument to
read, and therefore nothing known about `X` beyond three letters that happen to
look like a feature matrix.

Both modes must stay silent, and `--dataflow ip` must stay silent for the right
reason: the interprocedural summary over **zero** call sites is the empty set,
not the union of everything the name suggests.

# MLVIEW-EXPECT-NONE: MLV101, MLV102, MLV103
"""
from __future__ import annotations

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def fit_scaler(X, y):
    """Nothing in this workspace calls this, so nothing is known about `X`."""
    scaler = StandardScaler()
    scaled = scaler.fit_transform(X)
    return train_test_split(scaled, y, test_size=0.2, random_state=0)
