"""A trimmed HRNet: parallel multi-resolution branches with repeated fusion,
and a 1x1 head that emits one heatmap plane per joint.

The head has no activation on purpose - the target is a Gaussian in [0, 1] and
the objective is a plain MSE, so a sigmoid here would only compress the
gradient near the peak.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F

BN_MOMENTUM = 0.1


def conv3x3(in_planes: int, out_planes: int, stride: int = 1) -> nn.Conv2d:
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, in_planes: int, planes: int, stride: int = 1,
                 downsample=None) -> None:
        super().__init__()
        self.conv1 = conv3x3(in_planes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.downsample = downsample

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x if self.downsample is None else self.downsample(x)
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return self.relu(out + residual)


class Branch(nn.Module):
    """One resolution: four BasicBlocks at a fixed channel width."""

    def __init__(self, channels: int, blocks: int = 4) -> None:
        super().__init__()
        self.blocks = nn.Sequential(*[BasicBlock(channels, channels)
                                      for _ in range(blocks)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.blocks(x)


class FuseLayer(nn.Module):
    """Upsample the coarse branch and add it to the fine one."""

    def __init__(self, low_channels: int, high_channels: int) -> None:
        super().__init__()
        self.project = nn.Conv2d(low_channels, high_channels, 1, 1, 0, bias=False)
        self.norm = nn.BatchNorm2d(high_channels, momentum=BN_MOMENTUM)

    def forward(self, high: torch.Tensor, low: torch.Tensor) -> torch.Tensor:
        projected = self.norm(self.project(low))
        upsampled = F.interpolate(projected, size=high.shape[-2:],
                                  mode="bilinear", align_corners=False)
        return high + upsampled


class PoseHighResolutionNet(nn.Module):
    def __init__(self, width: int = 32, num_joints: int = 17) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 64, 3, 2, 1, bias=False),
            nn.BatchNorm2d(64, momentum=BN_MOMENTUM),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, 3, 2, 1, bias=False),
            nn.BatchNorm2d(64, momentum=BN_MOMENTUM),
            nn.ReLU(inplace=True),
        )
        self.entry = nn.Conv2d(64, width, 1, 1, 0, bias=False)
        self.down = nn.Conv2d(width, width * 2, 3, 2, 1, bias=False)
        branches: List[nn.Module] = [Branch(width), Branch(width * 2)]
        self.branches = nn.ModuleList(branches)
        self.fuse = FuseLayer(width * 2, width)
        self.head = nn.Conv2d(width, num_joints, kernel_size=1, stride=1, padding=0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        stem = self.stem(x)
        high = self.entry(stem)
        low = self.down(high)
        high = self.branches[0](high)
        low = self.branches[1](low)
        fused = self.fuse(high, low)
        return self.head(fused)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
