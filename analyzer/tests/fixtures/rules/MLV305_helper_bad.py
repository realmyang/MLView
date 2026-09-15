# MLVIEW-EXPECT: MLV305 line=31 confidence>=0.6 severity=medium
"""R4: the probabilities reach the metric through a helper and a tensor tail.

`probabilities()` is an ordinary workspace function whose `return` is the
softmax, and `.detach().cpu().numpy()` is what every torch program writes
before it hands a tensor to sklearn. Neither step changes what the value is,
and until the value-typing pass existed the tag was dropped at the first one.
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


def probabilities(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """Softmax over the class axis - still a continuous score."""
    return F.softmax(model(x), dim=-1)


def report(model: nn.Module, x: torch.Tensor, y) -> float:
    scores = probabilities(model, x)
    return accuracy_score(y, scores.detach().cpu().numpy())
