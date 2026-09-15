# MLVIEW-EXPECT: MLV402 confidence>=0.6 severity=high
"""R4: the sigmoid is in a helper and the logits loss is in the training step.

`BCEWithLogitsLoss` applies the sigmoid itself, so squashing first saturates the
gradient. The two halves are in different functions, which is why the pairing
was invisible.
"""
import torch
import torch.nn as nn


class BinaryHead(nn.Module):
    def __init__(self, features: int = 12) -> None:
        super().__init__()
        self.head = nn.Linear(features, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def squashed(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    return torch.sigmoid(model(x))


def step(model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    criterion = nn.BCEWithLogitsLoss()
    scores = squashed(model, x)
    return criterion(scores, y)
