"""A single-stage detector (defective twin).

Defect F: the three detection heads live in a plain Python list, so they are
never registered as submodules - `model.parameters()` does not see them, the
optimiser never updates them and `.to(device)` leaves them on the CPU.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn

from boxes import ANCHOR_SIZES


def conv_bn_act(cin: int, cout: int, kernel: int = 3, stride: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, kernel, stride=stride, padding=kernel // 2, bias=False),
        nn.BatchNorm2d(cout),
        nn.SiLU(inplace=True),
    )


class Bottleneck(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.reduce = conv_bn_act(channels, channels // 2, kernel=1)
        self.expand = conv_bn_act(channels // 2, channels, kernel=3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.expand(self.reduce(x))


class Backbone(nn.Module):
    """Three downsampling stages; the last three feature maps go to the neck."""

    def __init__(self, width: int = 64) -> None:
        super().__init__()
        self.stem = conv_bn_act(3, width, kernel=6, stride=2)
        self.stage1 = nn.Sequential(conv_bn_act(width, width * 2, stride=2),
                                    Bottleneck(width * 2))
        self.stage2 = nn.Sequential(conv_bn_act(width * 2, width * 4, stride=2),
                                    Bottleneck(width * 4))
        self.stage3 = nn.Sequential(conv_bn_act(width * 4, width * 8, stride=2),
                                    Bottleneck(width * 8))

    def forward(self, x: torch.Tensor) -> List[torch.Tensor]:
        x = self.stem(x)
        c3 = self.stage1(x)
        c4 = self.stage2(c3)
        c5 = self.stage3(c4)
        return [c3, c4, c5]


class FeaturePyramid(nn.Module):
    """Top-down lateral fusion over the three backbone levels."""

    def __init__(self, channels: tuple = (128, 256, 512), out: int = 128) -> None:
        super().__init__()
        self.lateral = nn.ModuleList([conv_bn_act(c, out, kernel=1) for c in channels])
        self.smooth = nn.ModuleList([conv_bn_act(out, out, kernel=3) for _ in channels])
        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")

    def forward(self, features: List[torch.Tensor]) -> List[torch.Tensor]:
        laterals = [layer(feature) for layer, feature in zip(self.lateral, features)]
        for index in range(len(laterals) - 1, 0, -1):
            laterals[index - 1] = laterals[index - 1] + self.upsample(laterals[index])
        return [layer(lateral) for layer, lateral in zip(self.smooth, laterals)]


class DetectionHead(nn.Module):
    """One 3x3 stack, then a classification and a regression 1x1."""

    def __init__(self, channels: int = 128, classes: int = 80,
                 anchors: int = 3) -> None:
        super().__init__()
        self.stem = nn.Sequential(conv_bn_act(channels, channels),
                                  conv_bn_act(channels, channels))
        self.cls = nn.Conv2d(channels, anchors * classes, 1)
        self.box = nn.Conv2d(channels, anchors * 4, 1)
        self.classes = classes
        self.anchors = anchors

    def forward(self, feature: torch.Tensor):
        shared = self.stem(feature)
        batch = shared.shape[0]
        cls_logits = (self.cls(shared)
                      .permute(0, 2, 3, 1)
                      .reshape(batch, -1, self.classes))
        box_deltas = (self.box(shared)
                      .permute(0, 2, 3, 1)
                      .reshape(batch, -1, 4))
        return cls_logits, box_deltas


class Detector(nn.Module):
    """backbone -> neck -> per-level head, concatenated over levels."""

    def __init__(self, classes: int = 80, width: int = 64) -> None:
        super().__init__()
        self.backbone = Backbone(width=width)
        self.neck = FeaturePyramid(channels=(width * 2, width * 4, width * 8))
        self.heads = [
            DetectionHead(classes=classes, anchors=len(sizes))
            for sizes in ANCHOR_SIZES
        ]

    def forward(self, images: torch.Tensor):
        features = self.neck(self.backbone(images))
        cls_out, box_out = [], []
        for head, feature in zip(self.heads, features):
            cls_logits, box_deltas = head(feature)
            cls_out.append(cls_logits)
            box_out.append(box_deltas)
        return torch.cat(cls_out, dim=1), torch.cat(box_out, dim=1)


def build_detector(classes: int = 80) -> Detector:
    return Detector(classes=classes)
