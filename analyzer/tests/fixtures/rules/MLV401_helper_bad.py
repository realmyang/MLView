# MLVIEW-EXPECT: MLV401 confidence>=0.6 severity=high
"""R4: the softmax is inside a helper, and CrossEntropyLoss is a `def` away.

`forward` returns raw logits, which is correct; the mistake is one level up, in
a scoring helper that softmaxes before handing the tensor to the loss. Tracing
only the model class finds nothing here.
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


def normalised_scores(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    return F.softmax(model(x), dim=-1)


def step(model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    scores = normalised_scores(model, x)
    return F.cross_entropy(scores, y)
