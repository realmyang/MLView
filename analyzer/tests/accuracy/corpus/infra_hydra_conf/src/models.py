"""The two architectures the registry can build. Both return logits."""
from __future__ import annotations

import torch
import torch.nn as nn


class ResNetTiny(nn.Module):
    def __init__(self, width: int = 64, depth: int = 3, dropout: float = 0.2,
                 classes: int = 10) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, width, 3, padding=1, bias=False),
            nn.BatchNorm2d(width),
            nn.ReLU(inplace=True),
        )
        self.stages = nn.ModuleList([
            nn.Sequential(
                nn.Conv2d(width, width, 3, padding=1, bias=False),
                nn.BatchNorm2d(width),
                nn.ReLU(inplace=True),
                nn.Dropout(dropout),
            )
            for _ in range(depth)
        ])
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        for stage in self.stages:
            h = h + stage(h)
        return self.head(self.pool(h).flatten(1))


class WideMLP(nn.Module):
    def __init__(self, width: int = 512, depth: int = 2, dropout: float = 0.1,
                 classes: int = 10) -> None:
        super().__init__()
        layers = []
        in_features = 3 * 32 * 32
        for _ in range(depth):
            layers += [nn.Linear(in_features, width), nn.GELU(),
                       nn.Dropout(dropout)]
            in_features = width
        self.body = nn.Sequential(*layers)
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x.flatten(1)))
