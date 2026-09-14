# MLVIEW-EXPECT: MLV301 confidence>=0.7
"""H5: the evaluation loop sits inside a `with` block, so `model.eval()` has to
be inserted at the loop's indentation - inside the block - and not at the
function's.

This is the shape the roadmap entry named: "indentation-correct inside with/for
blocks". A splice that guessed four spaces would put the call outside the
context manager and, at the wrong depth, outside the `with` entirely.
"""
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
        return self.fc2(self.drop(F.relu(self.norm(self.fc1(x)))))


def score(model: Net, val_loader: DataLoader) -> float:
    torch.manual_seed(0)
    correct = 0
    total = 0
    with torch.no_grad():
        for features, labels in val_loader:
            preds = model(features).argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)
    return correct / max(total, 1)
