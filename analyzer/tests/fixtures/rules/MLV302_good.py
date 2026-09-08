# MLVIEW-EXPECT-NONE: MLV302
"""The trap: no `with torch.no_grad():` block anywhere - the gradient context
comes from an @torch.inference_mode() decorator on one function and from an
enclosing no_grad block on the other, plus a saliency loop that genuinely
needs gradients."""
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


@torch.inference_mode()
def validate(model: Net, val_loader: DataLoader) -> float:
    torch.manual_seed(0)
    model.eval()
    correct = 0
    total = 0
    for features, labels in val_loader:
        preds = model(features).argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    return correct / max(total, 1)


def saliency(model: Net, val_loader: DataLoader):
    model.eval()
    maps = []
    for features, labels in val_loader:
        features.requires_grad_(True)
        maps.append(model(features).max())
    return maps
