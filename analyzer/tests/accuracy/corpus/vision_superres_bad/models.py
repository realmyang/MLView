"""The same ESRGAN pieces with the perceptual extractor left unfrozen.

`VGGFeatures` no longer pins itself to eval mode and no longer disables
gradients, so the perceptual term back-propagates into ImageNet weights that
nothing optimises and the extractor's own dropout is active while it measures
the distance the generator is scored on.
"""

from __future__ import annotations

from typing import List

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models as tv_models


class DenseBlock(nn.Module):
    """Five convolutions with dense skips - the RRDB building block."""

    def __init__(self, channels: int = 64, growth: int = 32) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(channels, growth, 3, 1, 1)
        self.conv2 = nn.Conv2d(channels + growth, growth, 3, 1, 1)
        self.conv3 = nn.Conv2d(channels + 2 * growth, growth, 3, 1, 1)
        self.conv4 = nn.Conv2d(channels + 3 * growth, growth, 3, 1, 1)
        self.conv5 = nn.Conv2d(channels + 4 * growth, channels, 3, 1, 1)
        self.act = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.act(self.conv1(x))
        x2 = self.act(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.act(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.act(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, channels: int = 64, growth: int = 32) -> None:
        super().__init__()
        self.blocks = nn.ModuleList([DenseBlock(channels, growth) for _ in range(3)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = x
        for block in self.blocks:
            out = block(out)
        return out * 0.2 + x


class Generator(nn.Module):
    """Low-resolution in, 4x super-resolved out. No output activation."""

    def __init__(self, channels: int = 64, blocks: int = 16, scale: int = 4) -> None:
        super().__init__()
        self.head = nn.Conv2d(3, channels, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(channels) for _ in range(blocks)])
        self.body_out = nn.Conv2d(channels, channels, 3, 1, 1)
        upsamples: List[nn.Module] = []
        for _ in range(int(scale // 2)):
            upsamples.append(nn.Conv2d(channels, channels * 4, 3, 1, 1))
            upsamples.append(nn.PixelShuffle(2))
            upsamples.append(nn.LeakyReLU(negative_slope=0.2, inplace=True))
        self.upsample = nn.Sequential(*upsamples)
        self.tail = nn.Sequential(
            nn.Conv2d(channels, channels, 3, 1, 1),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.Conv2d(channels, 3, 3, 1, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        feat = self.head(x)
        feat = feat + self.body_out(self.body(feat))
        feat = self.upsample(feat)
        return self.tail(feat)


class Discriminator(nn.Module):
    """Returns a raw score per image - there is no output activation."""

    def __init__(self, channels: int = 64) -> None:
        super().__init__()
        layers: List[nn.Module] = []
        in_channels = 3
        for index, out_channels in enumerate([channels, channels * 2,
                                              channels * 4, channels * 8]):
            layers.append(nn.Conv2d(in_channels, out_channels, 3, 1, 1, bias=False))
            if index > 0:
                layers.append(nn.BatchNorm2d(out_channels))
            layers.append(nn.LeakyReLU(negative_slope=0.2, inplace=True))
            layers.append(nn.Conv2d(out_channels, out_channels, 4, 2, 1, bias=False))
            layers.append(nn.BatchNorm2d(out_channels))
            layers.append(nn.LeakyReLU(negative_slope=0.2, inplace=True))
            in_channels = out_channels
        self.features = nn.Sequential(*layers)
        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(in_channels, 128),
            nn.LeakyReLU(negative_slope=0.2, inplace=True),
            nn.Linear(128, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


class VGGFeatures(nn.Module):
    """VGG19 truncated before the 5th max-pool - and no longer frozen."""

    IMAGENET_MEAN = (0.485, 0.456, 0.406)
    IMAGENET_STD = (0.229, 0.224, 0.225)

    def __init__(self, layer: int = 34) -> None:
        super().__init__()
        backbone = tv_models.vgg19(weights=tv_models.VGG19_Weights.DEFAULT)
        self.slice = nn.Sequential(*list(backbone.features.children())[:layer])
        # DEFECT: requires_grad_(False) is gone, so the perceptual term builds
        # a graph through 20 million ImageNet weights that no optimizer owns.
        # DEFECT: the eval() pin and the train() override are gone, so
        # generator.train() puts the extractor into training mode with it.
        self.register_buffer("mean", torch.tensor(self.IMAGENET_MEAN).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(self.IMAGENET_STD).view(1, 3, 1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.slice((x - self.mean) / self.std)


def psnr(prediction: torch.Tensor, target: torch.Tensor,
         max_value: float = 1.0) -> torch.Tensor:
    """DEFECT: this used to return a Python float and now returns a tensor."""
    mse = F.mse_loss(prediction, target)
    return 10.0 * torch.log10(max_value ** 2 / mse)
