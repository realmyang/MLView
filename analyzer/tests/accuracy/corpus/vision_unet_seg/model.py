"""A U-Net, and the Dice + BCE objective that goes with it.

The head is a bare 1x1 convolution: it returns logits, and every consumer
applies its own sigmoid. `BCEWithLogitsLoss` does it internally, the Dice term
does it explicitly, and the IoU metric thresholds the sigmoid.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F


class DoubleConv(nn.Module):
    """(conv -> BN -> ReLU) twice, the U-Net building block."""

    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(cin, cout, 3, padding=1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
            nn.Conv2d(cout, cout, 3, padding=1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class UNet(nn.Module):
    """Four down stages, a bottleneck, four up stages with skip connections."""

    def __init__(self, in_channels: int = 3, classes: int = 1,
                 features: tuple = (64, 128, 256, 512)) -> None:
        super().__init__()
        self.downs = nn.ModuleList()
        self.ups = nn.ModuleList()
        self.pool = nn.MaxPool2d(kernel_size=2, stride=2)

        channels = in_channels
        for feature in features:
            self.downs.append(DoubleConv(channels, feature))
            channels = feature

        self.bottleneck = DoubleConv(features[-1], features[-1] * 2)
        self.dropout = nn.Dropout2d(p=0.1)

        for feature in reversed(features):
            self.ups.append(nn.ConvTranspose2d(feature * 2, feature, 2, stride=2))
            self.ups.append(DoubleConv(feature * 2, feature))

        self.head = nn.Conv2d(features[0], classes, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips: List[torch.Tensor] = []
        for down in self.downs:
            x = down(x)
            skips.append(x)
            x = self.pool(x)

        x = self.dropout(self.bottleneck(x))
        skips = skips[::-1]

        for index in range(0, len(self.ups), 2):
            x = self.ups[index](x)
            skip = skips[index // 2]
            if x.shape[-2:] != skip.shape[-2:]:
                x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear",
                                  align_corners=False)
            x = self.ups[index + 1](torch.cat([skip, x], dim=1))

        return self.head(x)


class DiceBCELoss(nn.Module):
    """BCE over logits plus a soft Dice term computed on the sigmoid."""

    def __init__(self, dice_weight: float = 0.5, smooth: float = 1.0) -> None:
        super().__init__()
        self.bce = nn.BCEWithLogitsLoss()
        self.dice_weight = dice_weight
        self.smooth = smooth

    def dice_term(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probabilities = torch.sigmoid(logits)
        numerator = 2.0 * (probabilities * targets).sum(dim=(1, 2, 3)) + self.smooth
        denominator = (probabilities.sum(dim=(1, 2, 3))
                       + targets.sum(dim=(1, 2, 3)) + self.smooth)
        return 1.0 - (numerator / denominator).mean()

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return ((1.0 - self.dice_weight) * self.bce(logits, targets)
                + self.dice_weight * self.dice_term(logits, targets))


def iou_score(logits: torch.Tensor, targets: torch.Tensor,
              threshold: float = 0.5) -> float:
    """Intersection over union of the thresholded prediction - never the logits."""
    predicted = (torch.sigmoid(logits) > threshold).float()
    intersection = (predicted * targets).sum()
    union = predicted.sum() + targets.sum() - intersection
    return float((intersection + 1e-6) / (union + 1e-6))


def build_model(classes: int = 1) -> UNet:
    return UNet(classes=classes)
