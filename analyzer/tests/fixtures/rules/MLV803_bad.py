# MLVIEW-EXPECT: MLV803 line=19 confidence>=0.6
# MLVIEW-EXPECT: MLV803 line=23 confidence>=0.6
"""The whole module is pickled rather than its state_dict, and the checkpoint is
read back with neither map_location= nor weights_only=."""
import torch
import torch.nn as nn


class Net(nn.Module):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def save(model: nn.Module, path: str = "runs/best.pt") -> None:
    torch.save(model, path)


def restore(path: str = "runs/best.pt") -> nn.Module:
    return torch.load(path)
