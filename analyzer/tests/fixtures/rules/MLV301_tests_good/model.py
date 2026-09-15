"""The model under test - dropout and batch norm, so eval() would matter."""
import torch.nn as nn


class Net(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.body = nn.Sequential(nn.Linear(8, 8), nn.Dropout(0.5), nn.Linear(8, 2))

    def forward(self, x):
        return self.body(x)
