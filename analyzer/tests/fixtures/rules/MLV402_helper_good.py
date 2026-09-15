# MLVIEW-EXPECT-NONE: MLV402, MLV401
"""The trap: the same two `def`s, paired correctly.

`raw()` hands back unsquashed logits and `BCEWithLogitsLoss` applies the
sigmoid itself, which is the pairing the rule's fix hint asks for. The sigmoid
that does appear is applied to a detached copy, for reporting.
"""
import torch
import torch.nn as nn


class BinaryHead(nn.Module):
    def __init__(self, features: int = 12) -> None:
        super().__init__()
        self.head = nn.Linear(features, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def raw(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    return model(x)


def step(model: nn.Module, x: torch.Tensor, y: torch.Tensor):
    criterion = nn.BCEWithLogitsLoss()
    logits = raw(model, x)
    loss = criterion(logits, y)
    return loss, torch.sigmoid(logits.detach())
