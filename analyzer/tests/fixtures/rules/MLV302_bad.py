# MLVIEW-EXPECT: MLV302 line=25 confidence>=0.6 severity=medium
"""The evaluation loop builds an autograd graph nobody ever backpropagates."""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(64, 32)
        self.drop = nn.Dropout(0.5)
        self.fc2 = nn.Linear(32, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.drop(F.relu(self.fc1(x))))


def validate(model: Net, val_loader: DataLoader) -> float:
    torch.manual_seed(0)
    model.eval()
    correct = 0
    total = 0
    for features, labels in val_loader:
        preds = model(features).argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    model.train()
    return correct / max(total, 1)
