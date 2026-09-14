"""Two call sites, two containers: the parameter stays unresolved.

Intersection, never union. A union would pick one of the two and MLV112 would
report a worker count this program never uses.
"""
from __future__ import annotations

from torch.utils.data import DataLoader, TensorDataset

CONFIG = {"workers": 7}
OPTIONS = {"workers": 9}


def make(cfg):
    return DataLoader(TensorDataset(), num_workers=cfg["workers"])


first = make(CONFIG)
second = make(OPTIONS)
