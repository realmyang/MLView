"""A workspace module a registry selects from by name."""
from __future__ import annotations

import torch.nn as nn


class Alpha(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.head = nn.Linear(8, 2)

    def forward(self, x):
        return self.head(x)


class Beta(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.head = nn.Linear(8, 4)

    def forward(self, x):
        return self.head(x)
