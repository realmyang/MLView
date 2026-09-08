# MLVIEW-EXPECT: MLV701 line=11 confidence>=0.6 severity=high
"""An nn.Module whose __init__ forgets super().__init__()."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class Encoder(nn.Module):
    """The registries inherited from nn.Module are never built."""

    def __init__(self, width: int = 32) -> None:
        self.fc1 = nn.Linear(64, width)
        self.fc2 = nn.Linear(width, 10)
        self.drop = nn.Dropout(0.2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.relu(self.fc1(x))
        return self.fc2(self.drop(x))
