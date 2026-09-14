"""A small ResNet-shaped classifier plus the exponential moving average.

`forward` returns raw logits. The loss is `nn.CrossEntropyLoss`, which applies
log-softmax itself, so nothing here normalises the head's output.
"""

from __future__ import annotations

import copy

import torch
import torch.nn as nn
import torch.nn.functional as F

from config import CFG


class BasicBlock(nn.Module):
    """Two 3x3 convolutions with a projection shortcut when shapes differ."""

    expansion = 1

    def __init__(self, cin: int, cout: int, stride: int = 1) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, kernel_size=3, stride=stride,
                               padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(cout)
        self.conv2 = nn.Conv2d(cout, cout, kernel_size=3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(cout)
        self.downsample = None
        if stride != 1 or cin != cout:
            self.downsample = nn.Sequential(
                nn.Conv2d(cin, cout, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(cout),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x if self.downsample is None else self.downsample(x)
        out = F.relu(self.bn1(self.conv1(x)), inplace=True)
        out = self.bn2(self.conv2(out))
        return F.relu(out + identity, inplace=True)


class ResNetish(nn.Module):
    """Stem, four stages of BasicBlocks, global pool, linear head."""

    def __init__(self, classes: int = 1000, width: int = 64,
                 layers: tuple = (2, 2, 2, 2)) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, width, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(width),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1),
        )
        stages = []
        cin = width
        for index, count in enumerate(layers):
            cout = width * (2 ** index)
            stride = 1 if index == 0 else 2
            blocks = [BasicBlock(cin, cout, stride=stride)]
            blocks += [BasicBlock(cout, cout) for _ in range(count - 1)]
            stages.append(nn.Sequential(*blocks))
            cin = cout
        self.stages = nn.ModuleList(stages)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(p=0.2)
        self.head = nn.Linear(cin, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.stem(x)
        for stage in self.stages:
            x = stage(x)
        x = self.pool(x).flatten(1)
        return self.head(self.dropout(x))


class ModelEma(nn.Module):
    """Exponential moving average of the trained weights.

    The shadow copy is a real `nn.Module` so `state_dict()` round-trips, and
    the update runs under `no_grad` because it is arithmetic on parameters,
    not a step of the optimisation.
    """

    def __init__(self, model: nn.Module, decay: float = CFG.ema_decay) -> None:
        super().__init__()
        self.module = copy.deepcopy(model)
        self.module.eval()
        self.decay = decay
        for parameter in self.module.parameters():
            parameter.requires_grad_(False)

    @torch.no_grad()
    def update(self, model: nn.Module) -> None:
        shadow = dict(self.module.named_parameters())
        for name, value in model.named_parameters():
            shadow[name].mul_(self.decay).add_(value.detach(), alpha=1.0 - self.decay)
        shadow_buffers = dict(self.module.named_buffers())
        for name, value in model.named_buffers():
            shadow_buffers[name].copy_(value)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.module(x)


def build_model(classes: int = 1000) -> ResNetish:
    return ResNetish(classes=classes)


def build_criterion() -> nn.Module:
    """Logits in, so no activation on the head and no softmax anywhere."""
    return nn.CrossEntropyLoss(label_smoothing=CFG.label_smoothing)
