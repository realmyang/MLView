"""Everything the registry can build. Importing this module is the registration.

Two models, two losses and two optimizer factories, each behind a decorator.
The classes themselves are ordinary and correct: both call `super().__init__()`,
both return raw logits, and the focal loss takes logits and applies its own
`binary_cross_entropy_with_logits`, so there is no sigmoid/BCE mismatch here.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from registry import LOSSES, MODELS, OPTIMIZERS


@MODELS.register("wide_resnet")
class WideResNet(nn.Module):
    def __init__(self, features: int = 64, width: int = 256,
                 classes: int = 10, dropout: float = 0.2) -> None:
        super().__init__()
        self.stem = nn.Sequential(nn.Linear(features, width), nn.GELU())
        self.blocks = nn.ModuleList(
            nn.Sequential(nn.LayerNorm(width), nn.Linear(width, width),
                          nn.GELU(), nn.Dropout(dropout),
                          nn.Linear(width, width))
            for _ in range(4))
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        for block in self.blocks:
            h = h + block(h)
        return self.head(h)


@MODELS.register("tiny_mlp")
class TinyMLP(nn.Module):
    def __init__(self, features: int = 64, width: int = 64,
                 classes: int = 10) -> None:
        super().__init__()
        self.body = nn.Sequential(nn.Linear(features, width), nn.ReLU(),
                                  nn.Dropout(0.1))
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


@LOSSES.register("cross_entropy")
def cross_entropy(label_smoothing: float = 0.0) -> nn.Module:
    return nn.CrossEntropyLoss(label_smoothing=label_smoothing)


@LOSSES.register("focal")
class FocalLoss(nn.Module):
    """Takes **logits** and applies BCE-with-logits itself - no sigmoid outside."""

    def __init__(self, gamma: float = 2.0, alpha: float = 0.25) -> None:
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha

    def forward(self, logits: torch.Tensor,
                targets: torch.Tensor) -> torch.Tensor:
        one_hot = F.one_hot(targets, logits.shape[-1]).float()
        bce = F.binary_cross_entropy_with_logits(logits, one_hot,
                                                 reduction="none")
        probability = torch.exp(-bce)
        weight = self.alpha * (1.0 - probability) ** self.gamma
        return (weight * bce).mean()


@OPTIMIZERS.register("adamw")
def adamw(parameters, lr: float = 1e-3, weight_decay: float = 0.01):
    return torch.optim.AdamW(parameters, lr=lr, weight_decay=weight_decay)


@OPTIMIZERS.register("sgd")
def sgd(parameters, lr: float = 0.1, momentum: float = 0.9):
    return torch.optim.SGD(parameters, lr=lr, momentum=momentum,
                           nesterov=True)
