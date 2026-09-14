"""The same LSTM head as the clean twin.

The model is not where the defects are. It calls `super().__init__()`, it
registers its submodules as attributes and as an `nn.Sequential`, and it
returns raw values for a regression loss. Every planted defect in this project
lives in `windows.py` and `train.py`.
"""
from __future__ import annotations

import torch
from torch import nn

from windows import FEATURES, HORIZON


class LoadForecaster(nn.Module):
    def __init__(self, n_features: int = len(FEATURES), hidden: int = 128,
                 layers: int = 2, horizon: int = HORIZON, dropout: float = 0.1):
        super().__init__()
        self.encoder = nn.LSTM(input_size=n_features, hidden_size=hidden,
                               num_layers=layers, batch_first=True,
                               dropout=dropout)
        self.norm = nn.LayerNorm(hidden)
        self.head = nn.Sequential(
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden // 2, horizon),
        )

    def forward(self, history: torch.Tensor) -> torch.Tensor:
        sequence, _state = self.encoder(history)
        last = self.norm(sequence[:, -1, :])
        return self.head(last)
