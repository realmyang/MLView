# MLVIEW-EXPECT: MLV301 line=28 confidence>=0.6 severity=high ghost=true
"""validate() never calls model.eval(), so Dropout and BatchNorm stay in
training mode and the reported validation accuracy is noise."""
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


def validate(model: Net, val_loader: DataLoader) -> float:
    torch.manual_seed(0)
    correct = 0
    total = 0
    with torch.no_grad():
        for features, labels in val_loader:
            logits = model(features)
            preds = logits.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)
    return correct / max(total, 1)
