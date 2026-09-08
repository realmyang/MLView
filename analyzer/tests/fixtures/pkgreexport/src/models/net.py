"""The network and its optimizer factory, published through `src.models`."""
import torch
import torch.nn as nn
import torch.optim as optim


class Net(nn.Module):
    def __init__(self, width: int = 16, hidden: int = 32) -> None:
        super().__init__()
        self.body = nn.Linear(width, hidden)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(torch.relu(self.body(x)))


def build_optimizer(model: nn.Module, lr: float = 1e-3) -> optim.Optimizer:
    return optim.Adam(model.parameters(), lr=lr)
