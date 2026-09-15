"""CRNN: a convolutional feature extractor collapsed to a width-major
sequence, a bidirectional LSTM over it, and a per-frame character classifier.

The head returns raw logits. CTC needs log-probabilities, and the training
script is the one place that applies `log_softmax`, so the logits stay reusable
for the confidence read-out on the serving path.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    """conv -> batch norm -> relu, with an optional asymmetric pooling."""

    def __init__(self, in_channels: int, out_channels: int,
                 pool: str = "both") -> None:
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1)
        self.norm = nn.BatchNorm2d(out_channels)
        self.act = nn.ReLU(inplace=True)
        if pool == "both":
            self.pool = nn.MaxPool2d(kernel_size=2, stride=2)
        elif pool == "height":
            # halve the height only: width is the CTC time axis and is precious
            self.pool = nn.MaxPool2d(kernel_size=(2, 1), stride=(2, 1))
        else:
            self.pool = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool(self.act(self.norm(self.conv(x))))


class BidirectionalLSTM(nn.Module):
    def __init__(self, in_size: int, hidden: int, out_size: int) -> None:
        super().__init__()
        self.rnn = nn.LSTM(in_size, hidden, bidirectional=True, batch_first=True)
        self.linear = nn.Linear(hidden * 2, out_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        recurrent, _state = self.rnn(x)
        return self.linear(recurrent)


class CRNN(nn.Module):
    def __init__(self, num_classes: int, channels: int = 1,
                 hidden: int = 256, dropout: float = 0.1) -> None:
        super().__init__()
        widths: List[int] = [64, 128, 256, 256, 512]
        pools = ["both", "both", "none", "height", "height"]
        blocks = []
        previous = channels
        for width, pool in zip(widths, pools):
            blocks.append(ConvBlock(previous, width, pool=pool))
            previous = width
        self.backbone = nn.ModuleList(blocks)
        self.dropout = nn.Dropout(dropout)
        self.sequence = BidirectionalLSTM(previous, hidden, hidden)
        self.classifier = nn.Linear(hidden, num_classes)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        features = images
        for block in self.backbone:
            features = block(features)
        # (N, C, H, W) -> (N, W, C*H): width becomes the CTC time axis
        features = features.permute(0, 3, 1, 2)
        batch, width, channels, height = features.shape
        features = features.reshape(batch, width, channels * height)
        features = self.dropout(features)
        features = self.sequence(features)
        return self.classifier(features)

    def downsampled_width(self, width: int) -> int:
        """The CTC input length for an image of this width."""
        return max(1, width // 4)


def build_model(num_classes: int, hidden: int = 256) -> CRNN:
    return CRNN(num_classes=num_classes, hidden=hidden)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
