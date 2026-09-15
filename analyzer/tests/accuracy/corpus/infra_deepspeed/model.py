"""The scoring head DeepSpeed shards. Logits out; the loss is built outside."""
from __future__ import annotations

import torch
import torch.nn as nn


class CaptionScorer(nn.Module):
    def __init__(self, in_features: int = 64, width: int = 512,
                 classes: int = 5, dropout: float = 0.1) -> None:
        super().__init__()
        self.project = nn.Linear(in_features, width)
        self.norm = nn.LayerNorm(width)
        self.body = nn.Sequential(
            nn.Linear(width, width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width // 2),
            nn.GELU(),
        )
        self.head = nn.Linear(width // 2, classes)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        hidden = self.norm(self.project(features))
        return self.head(self.body(hidden))
