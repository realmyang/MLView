"""The definitions half of the GRAPH-R3 fixture: workspace objects.

Nothing here is a defect. The fixture exists to measure what the **diagram**
recovers, so every shape is written the way a correct project writes it:

* an `nn.Module` subclass whose construction site is a `model` card;
* a loss class that is a loss because its `forward` returns one, not because of
  its name (`is_loss_class` is structural on purpose - see
  `core/workspace_ops.py`);
* a `Dataset` subclass;
* four factories, one per object kind the roadmap entry names - model,
  optimizer, scheduler, loaders - because a factory return that loses its
  identity loses everything downstream of it.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


class TinyNet(nn.Module):
    def __init__(self, width: int = 16) -> None:
        super().__init__()
        self.stem = nn.Linear(width, width)
        self.head = nn.Linear(width, 2)

    def forward(self, x):
        return self.head(F.relu(self.stem(x)))


class FocalLoss(nn.Module):
    """An `nn.Module` that is a **criterion**: its forward returns a loss."""

    def __init__(self, gamma: float = 2.0) -> None:
        super().__init__()
        self.gamma = gamma

    def forward(self, logits, target):
        return F.cross_entropy(logits, target)


class ShardDataset(Dataset):
    def __init__(self, path: str) -> None:
        self.path = path

    def __len__(self):
        return 8

    def __getitem__(self, index):
        return torch.zeros(16), 0


def build_model():
    return TinyNet(32)


def build_optimizer(model):
    return torch.optim.AdamW(model.parameters(), lr=1e-3)


def build_scheduler(optimizer):
    return torch.optim.lr_scheduler.StepLR(optimizer, step_size=5)


def build_loaders(path):
    train_ds = ShardDataset(path)
    val_ds = ShardDataset(path)
    return (DataLoader(train_ds, batch_size=8, shuffle=True),
            DataLoader(val_ds, batch_size=8, shuffle=False))
