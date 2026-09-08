# MLVIEW-EXPECT: MLV702 line=22 confidence>=0.6 severity=high
"""Submodules parked in a plain Python list are invisible to nn.Module."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, 3, padding=1)
        self.norm = nn.BatchNorm2d(cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.relu(self.norm(self.conv(x)))


class Tower(nn.Module):
    def __init__(self, depth: int = 4) -> None:
        super().__init__()
        self.stem = nn.Conv2d(3, 16, 3, padding=1)
        self.blocks = [ConvBlock(16, 16) for _ in range(depth)]
        self.head = nn.Linear(16, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem(x)
        for block in self.blocks:
            x = block(x)
        return self.head(x.mean(dim=(2, 3)))
