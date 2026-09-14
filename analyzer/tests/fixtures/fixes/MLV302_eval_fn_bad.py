# MLVIEW-EXPECT: MLV302 confidence>=0.7
"""H5: an evaluation function that builds an autograd graph nobody uses.

The fix is the **decorator** form, not the `with torch.no_grad():` wrap the fix
hint names: wrapping the loop would mean re-indenting every physical line of
the suite, and this module refuses to do that. `evaluate()` contains no
backward, no optimizer step and no zero_grad, which is what makes decorating
the whole function equivalent to wrapping the loop.
"""
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


def evaluate(model: Net, val_loader: DataLoader) -> float:
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
