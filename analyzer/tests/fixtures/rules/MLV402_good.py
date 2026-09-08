# MLVIEW-EXPECT-NONE: MLV402
"""The trap: both pairings are present and both are correct - raw logits into
BCEWithLogitsLoss, and an explicitly sigmoided tensor into BCELoss. A class
*named* Sigmoid that is not nn.Sigmoid must not change the answer."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class Sigmoid(nn.Module):
    """A user class that only shares the name - it is a plain scaling layer."""

    def __init__(self, scale: float = 1.0) -> None:
        super().__init__()
        self.scale = scale
        self.fc = nn.Linear(16, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(x) * self.scale


class LogitHead(nn.Module):
    def __init__(self, features: int = 10) -> None:
        super().__init__()
        self.fc1 = nn.Linear(features, 16)
        self.head = Sigmoid()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(F.relu(self.fc1(x)))


def logit_loss(model: LogitHead, features: torch.Tensor, labels: torch.Tensor):
    criterion = nn.BCEWithLogitsLoss()
    return criterion(model(features), labels)


def probability_loss(model: LogitHead, features: torch.Tensor, labels: torch.Tensor):
    criterion = nn.BCELoss()
    probs = torch.sigmoid(model(features))
    return criterion(probs, labels)
