"""WideResNet-28-2, the backbone every FixMatch reproduction uses.

Pre-activation residual blocks, leaky ReLU, and a BatchNorm whose momentum is
set to the value the reference implementation uses. The head returns logits.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F

BN_MOMENTUM = 0.001


class BasicBlock(nn.Module):
    def __init__(self, in_planes: int, out_planes: int, stride: int,
                 drop_rate: float = 0.0) -> None:
        super().__init__()
        self.bn1 = nn.BatchNorm2d(in_planes, momentum=BN_MOMENTUM)
        self.relu1 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.conv1 = nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                               padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_planes, momentum=BN_MOMENTUM)
        self.relu2 = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.conv2 = nn.Conv2d(out_planes, out_planes, kernel_size=3, stride=1,
                               padding=1, bias=False)
        self.drop_rate = drop_rate
        self.equal = in_planes == out_planes
        self.shortcut = None if self.equal else nn.Conv2d(
            in_planes, out_planes, kernel_size=1, stride=stride, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.relu1(self.bn1(x))
        identity = x if self.equal else self.shortcut(out)
        out = self.conv1(out)
        out = self.relu2(self.bn2(out))
        if self.drop_rate > 0.0:
            out = F.dropout(out, p=self.drop_rate, training=self.training)
        out = self.conv2(out)
        return out + identity


class NetworkBlock(nn.Module):
    def __init__(self, layers: int, in_planes: int, out_planes: int,
                 stride: int, drop_rate: float = 0.0) -> None:
        super().__init__()
        blocks: List[nn.Module] = []
        for index in range(layers):
            blocks.append(BasicBlock(in_planes if index == 0 else out_planes,
                                     out_planes,
                                     stride if index == 0 else 1,
                                     drop_rate))
        self.layer = nn.Sequential(*blocks)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layer(x)


class WideResNet(nn.Module):
    def __init__(self, depth: int = 28, widen_factor: int = 2,
                 num_classes: int = 10, drop_rate: float = 0.0) -> None:
        super().__init__()
        channels = [16, 16 * widen_factor, 32 * widen_factor, 64 * widen_factor]
        assert (depth - 4) % 6 == 0
        layers = (depth - 4) // 6
        self.conv1 = nn.Conv2d(3, channels[0], kernel_size=3, stride=1,
                               padding=1, bias=False)
        self.block1 = NetworkBlock(layers, channels[0], channels[1], 1, drop_rate)
        self.block2 = NetworkBlock(layers, channels[1], channels[2], 2, drop_rate)
        self.block3 = NetworkBlock(layers, channels[2], channels[3], 2, drop_rate)
        self.bn1 = nn.BatchNorm2d(channels[3], momentum=BN_MOMENTUM)
        self.relu = nn.LeakyReLU(negative_slope=0.1, inplace=True)
        self.fc = nn.Linear(channels[3], num_classes)
        self.channels = channels[3]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.conv1(x)
        out = self.block1(out)
        out = self.block2(out)
        out = self.block3(out)
        out = self.relu(self.bn1(out))
        out = F.adaptive_avg_pool2d(out, 1)
        out = out.view(-1, self.channels)
        return self.fc(out)
