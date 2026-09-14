"""The classifier. Logits out; the loss is built in `engine/trainer.py`."""
from __future__ import annotations

import torch
import torch.nn as nn

from ..config import TrainConfig


class CreditMLP(nn.Module):
    def __init__(self, in_features: int, hidden: int = 256,
                 dropout: float = 0.2, classes: int = 2) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(in_features, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
        )
        self.head = nn.Linear(hidden // 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))

    @classmethod
    def from_config(cls, cfg: TrainConfig) -> "CreditMLP":
        return cls(in_features=len(cfg.features), hidden=cfg.hidden,
                   dropout=cfg.dropout)
