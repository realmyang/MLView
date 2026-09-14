"""The model both DDP twins train. Logits out, no activation on the head."""
from __future__ import annotations

import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    def __init__(self, width: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(width)
        self.fc1 = nn.Linear(width, width * 2)
        self.fc2 = nn.Linear(width * 2, width)
        self.drop = nn.Dropout(dropout)
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.norm(x)
        h = self.fc2(self.drop(self.act(self.fc1(h))))
        return x + h


class ResidualMLP(nn.Module):
    def __init__(self, in_features: int = 32, width: int = 128,
                 depth: int = 4, classes: int = 4) -> None:
        super().__init__()
        self.stem = nn.Linear(in_features, width)
        self.blocks = nn.ModuleList(
            [ResidualBlock(width) for _ in range(depth)])
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        for block in self.blocks:
            h = block(h)
        return self.head(h)
