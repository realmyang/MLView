"""Every split this project knows how to make, in one place.

The job modules never call `train_test_split` themselves; they ask for a split
by name. That is good hygiene and it is also what makes the leak in
`registry.py` hard to see in review: the split and the fit are three files
apart.
"""
from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split

SEED = 512


def stratified_split(features, labels, test_size: float = 0.2):
    return train_test_split(features, labels, test_size=test_size,
                            stratify=labels, random_state=SEED)


def chronological_split(frame: pd.DataFrame, timestamp: str,
                        holdout_days: int = 30):
    cutoff = frame[timestamp].max() - pd.Timedelta(days=holdout_days)
    return frame.loc[frame[timestamp] <= cutoff], frame.loc[frame[timestamp] > cutoff]
