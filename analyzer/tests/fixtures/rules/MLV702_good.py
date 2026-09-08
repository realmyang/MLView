# MLVIEW-EXPECT-NONE: MLV702
"""The trap: a plain list of *configs* (never matched), and a plain list of
submodules that is handed to nn.Sequential on the next line (registered)."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.conv = nn.Conv2d(cin, cout, 3, padding=1)
        self.norm = nn.BatchNorm2d(cout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.relu(self.norm(self.conv(x)))


class Tower(nn.Module):
    def __init__(self, depth: int = 4) -> None:
        super().__init__()
        self.widths = [16, 32, 64, 128]
        self.stem = nn.Conv2d(3, 16, 3, padding=1)
        self.blocks = [ConvBlock(16, 16) for _ in range(depth)]
        self.body = nn.Sequential(*self.blocks)
        self.stages = nn.ModuleList([ConvBlock(16, 16) for _ in range(depth)])
        self.head = nn.Linear(16, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.body(self.stem(x))
        for stage in self.stages:
            x = stage(x)
        return self.head(x.mean(dim=(2, 3)))
