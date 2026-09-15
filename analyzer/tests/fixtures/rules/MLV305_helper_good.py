# MLVIEW-EXPECT-NONE: MLV305, MLV306, MLV401
"""The trap for R4's value typing: the same helper shape, done right.

`predictions()` takes the class decision inside the helper, so what comes back
is PREDS and `accuracy_score` is being handed exactly what it wants. A rule that
followed the helper's `return` but stopped reading at the softmax would accuse
this file, which is the failure mode the new pass is most likely to have.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import accuracy_score


class Classifier(nn.Module):
    def __init__(self, features: int = 8, classes: int = 3) -> None:
        super().__init__()
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def predictions(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """The class decision is taken here, so the caller gets hard labels."""
    return F.softmax(model(x), dim=-1).argmax(dim=-1)


def report(model: nn.Module, x: torch.Tensor, y) -> float:
    preds = predictions(model, x)
    return accuracy_score(y, preds.detach().cpu().numpy())
