# MLVIEW-EXPECT-NONE: MLV301
"""The trap: model.eval() is called once in the *caller*, not in validate()
itself, and validate() only receives the model as a parameter - the one-level
dominance search has to find it."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(64, 32)
        self.norm = nn.BatchNorm1d(32)
        self.drop = nn.Dropout(0.5)
        self.fc2 = nn.Linear(32, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = F.relu(self.norm(self.fc1(x)))
        return self.fc2(self.drop(x))


@torch.no_grad()
def validate(model: Net, val_loader: DataLoader) -> float:
    correct = 0
    total = 0
    for features, labels in val_loader:
        preds = model(features).argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    return correct / max(total, 1)


def run(model: Net, val_loader: DataLoader) -> float:
    torch.manual_seed(0)
    model.eval()
    score = validate(model, val_loader)
    model.train()
    return score
