"""Registered model factories, plus one built by getattr on the torch.nn module."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from registry import register


@register("model", "mlp")
class MLP(nn.Module):
    def __init__(self, features: int = 32, hidden: int = 128, classes: int = 4) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.head = nn.Linear(hidden, classes)

    def forward(self, x):
        return F.softmax(self.head(self.body(x)), dim=-1)


@register("model", "wide")
class WideMLP(nn.Module):
    def __init__(self, features: int = 32, classes: int = 4) -> None:
        self.head = nn.Linear(features, classes)

    def forward(self, x):
        return self.head(x)


def optimizer_for(model, cfg):
    factory = getattr(torch.optim, cfg["optimizer"])
    return factory(model.parameters(), lr=cfg["lr"])
