"""The module the `importlib.import_module` + `getattr` dispatch lands in.

Nothing dynamic lives here: two ordinary `nn.Module` subclasses, both calling
`super().__init__()`, both returning raw logits. They exist so that the dynamic
half of `train.py` has a real destination and the model lane has something true
to draw once the dispatch is followed — or, if it is not followed, so that the
`dynamic_scope` chip is measurably about one call and not about the project.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class WideMLP(nn.Module):
    def __init__(self, features: int = 48, classes: int = 6,
                 width: int = 256, dropout: float = 0.2) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, width),
            nn.BatchNorm1d(width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width // 2),
            nn.GELU(),
        )
        self.head = nn.Linear(width // 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


class ResidualMLP(nn.Module):
    def __init__(self, features: int = 48, classes: int = 6,
                 width: int = 192, blocks: int = 3) -> None:
        super().__init__()
        self.stem = nn.Linear(features, width)
        self.blocks = nn.ModuleList(
            nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width),
                          nn.GELU(), nn.Linear(width, width))
            for _ in range(blocks))
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        for block in self.blocks:
            h = h + block(h)
        return self.head(h)
