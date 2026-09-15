# MLVIEW-EXPECT-NONE: MLV401, MLV402
"""The trap: the same helper shape, returning logits.

`raw_scores()` is a helper whose `return` is a model forward, and the softmax
in this file is applied *after* the loss, for reporting - which is exactly
where it belongs. A pass that followed the helper's return and then matched any
softmax in the module would accuse this file.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class Tagger(nn.Module):
    def __init__(self, features: int = 16, classes: int = 5) -> None:
        super().__init__()
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def raw_scores(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    return model(x)


def step(model: nn.Module, x: torch.Tensor, y: torch.Tensor):
    logits = raw_scores(model, x)
    loss = F.cross_entropy(logits, y)
    return loss, F.softmax(logits.detach(), dim=-1)
