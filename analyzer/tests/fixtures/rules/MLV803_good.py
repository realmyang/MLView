# MLVIEW-EXPECT-NONE: MLV803
"""The trap: the same two calls on the same model, spelled the safe way - the
state_dict is what is pickled, and the load is pinned to the CPU with
weights_only=True. Matching torch.save/torch.load alone would fire here."""
import torch
import torch.nn as nn


class Net(nn.Module):
    def __init__(self, features: int = 16, classes: int = 3) -> None:
        super().__init__()
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(x)


def save(model: nn.Module, path: str = "runs/best.pt") -> None:
    torch.save(model.state_dict(), path)


def restore(path: str = "runs/best.pt") -> nn.Module:
    model = Net()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    return model
