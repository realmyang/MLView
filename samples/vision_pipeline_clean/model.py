"""The convolutional network - corrected twin.

Fix 5 (MLV702): the blocks live in an nn.ModuleList, so they are registered.
Fix 4 (MLV401): forward returns raw logits; CrossEntropyLoss log-softmaxes them.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from config import DEPTH, NUM_CLASSES, WIDTH


class ConvBlock(nn.Module):
    """Conv -> BatchNorm -> ReLU -> Dropout."""

    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, kernel_size=3, padding=1)
        self.norm = nn.BatchNorm2d(cout)
        self.drop = nn.Dropout(0.1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.drop(F.relu(self.norm(self.conv(x))))


class SmallCNN(nn.Module):
    """A four-block CIFAR-sized classifier."""

    def __init__(self, classes: int = NUM_CLASSES, width: int = WIDTH,
                 depth: int = DEPTH) -> None:
        super().__init__()
        self.stem = nn.Conv2d(3, width, kernel_size=3, padding=1)
        self.blocks = nn.ModuleList([ConvBlock(width, width) for _ in range(depth)])
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.relu(self.stem(x))
        for block in self.blocks:
            x = block(x)
        x = self.pool(x).flatten(1)
        return self.head(x)
