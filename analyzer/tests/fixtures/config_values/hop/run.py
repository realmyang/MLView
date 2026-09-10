"""One argument -> parameter hop: the container travels into `make`."""
from __future__ import annotations

from torch.utils.data import DataLoader, TensorDataset

CFG = {"workers": 5}


def make(cfg=CFG):
    return DataLoader(TensorDataset(), num_workers=cfg["workers"])


loader = make()
