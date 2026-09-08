# MLVIEW-EXPECT-NONE: MLV701
"""The trap: an abstract base with no super() call, and a subclass that chains
through the explicit `Base.__init__(self)` spelling rather than `super()`."""
from abc import abstractmethod

import torch
import torch.nn as nn
import torch.nn.functional as F


class BackboneBase(nn.Module):
    """Abstract - never instantiated, so it cannot fail at runtime."""

    def __init__(self) -> None:
        super().__init__()
        self.width = 32

    @abstractmethod
    def stem(self, x: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError


class Encoder(BackboneBase):
    def __init__(self, width: int = 32) -> None:
        BackboneBase.__init__(self)
        self.fc1 = nn.Linear(64, width)
        self.fc2 = nn.Linear(width, 10)

    def stem(self, x: torch.Tensor) -> torch.Tensor:
        return F.relu(self.fc1(x))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.stem(x))
