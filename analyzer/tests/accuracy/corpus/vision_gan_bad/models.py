"""DCGAN generator and discriminator (defective twin).

Defect 1: the discriminator ends in `nn.Sigmoid()` while the objective is
`BCEWithLogitsLoss`, so the sigmoid is applied twice and the discriminator's
gradient vanishes as soon as it is even slightly confident.
"""

from __future__ import annotations

import torch
import torch.nn as nn

LATENT_DIM = 128
FEATURE_MAP = 64
IMAGE_CHANNELS = 3


class Generator(nn.Module):
    """z -> 4x4 -> 8x8 -> 16x16 -> 32x32 -> 64x64, tanh output."""

    def __init__(self, latent_dim: int = LATENT_DIM, features: int = FEATURE_MAP,
                 channels: int = IMAGE_CHANNELS) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.ConvTranspose2d(latent_dim, features * 8, 4, 1, 0, bias=False),
            nn.BatchNorm2d(features * 8),
            nn.ReLU(True),
            nn.ConvTranspose2d(features * 8, features * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(features * 4),
            nn.ReLU(True),
            nn.ConvTranspose2d(features * 4, features * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(features * 2),
            nn.ReLU(True),
            nn.ConvTranspose2d(features * 2, features, 4, 2, 1, bias=False),
            nn.BatchNorm2d(features),
            nn.ReLU(True),
            nn.ConvTranspose2d(features, channels, 4, 2, 1, bias=False),
            nn.Tanh(),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.net(z)


class Discriminator(nn.Module):
    """Defect 1: a sigmoid head in front of a logits loss."""

    def __init__(self, features: int = FEATURE_MAP,
                 channels: int = IMAGE_CHANNELS) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(channels, features, 4, 2, 1, bias=False),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features, features * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(features * 2),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features * 2, features * 4, 4, 2, 1, bias=False),
            nn.BatchNorm2d(features * 4),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features * 4, 1, 4, 1, 0, bias=False),
            nn.Sigmoid(),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.net(images).view(-1)


class Critic(nn.Module):
    """The WGAN-GP critic: InstanceNorm, because the penalty is per-sample."""

    def __init__(self, features: int = FEATURE_MAP,
                 channels: int = IMAGE_CHANNELS) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(channels, features, 4, 2, 1),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features, features * 2, 4, 2, 1),
            nn.InstanceNorm2d(features * 2, affine=True),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features * 2, features * 4, 4, 2, 1),
            nn.InstanceNorm2d(features * 4, affine=True),
            nn.LeakyReLU(0.2, inplace=True),
            nn.Conv2d(features * 4, 1, 4, 1, 0),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.net(images).view(-1)


def weights_init(module: nn.Module) -> None:
    """The DCGAN paper's initialisation, applied with `model.apply`."""
    name = module.__class__.__name__
    if name.find("Conv") != -1:
        nn.init.normal_(module.weight.data, 0.0, 0.02)
    elif name.find("BatchNorm") != -1:
        nn.init.normal_(module.weight.data, 1.0, 0.02)
        nn.init.constant_(module.bias.data, 0)
