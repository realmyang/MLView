# MLVIEW-EXPECT-NONE: MLV301
"""H5: the clean twin of `MLV301_with_block_bad.py` - `model.eval()` already
stands inside the `with` block, exactly where the fix would have inserted it,
and `model.train()` is restored afterwards the way only a human can decide to.
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
        model.eval()
        for features, labels in val_loader:
            preds = model(features).argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)
    model.train()
    return correct / max(total, 1)
