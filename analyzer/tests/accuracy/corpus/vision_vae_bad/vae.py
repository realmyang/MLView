"""A convolutional VAE on 64x64 images (defective twin).

Defect 1: the decoder ends in `nn.Sigmoid()` while the reconstruction term is
still `binary_cross_entropy_with_logits`, so the sigmoid is applied twice and
the reconstruction gradient collapses.
Defect 2 (no rule covers it yet): the KL term's sign is flipped, so the
optimiser is rewarded for a *larger* divergence and the posterior runs away
from the prior.
Defect 3: the gradients are never zeroed.
Defect 4: the ELBO is accumulated as a live tensor across the whole run.
Defect 5: the sampler runs with the module in train mode and with autograd on,
so the BatchNorm statistics of the decoder are overwritten by pure noise.
Defect 6: the training loader does not shuffle.
"""

from __future__ import annotations

import random
from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import CelebA
from torchvision.utils import save_image

SEED = 6060
DATA_ROOT = "data/celeba"
LATENT = 128
EPOCHS = 60
BATCH_SIZE = 128
WORKERS = 6
LR = 1e-3
KL_WEIGHT = 1.0


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class Encoder(nn.Module):
    """Four strided convolutions, then two linear heads for mu and logvar."""

    def __init__(self, latent: int = LATENT, width: int = 32) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, width, 4, 2, 1), nn.BatchNorm2d(width), nn.ReLU(True),
            nn.Conv2d(width, width * 2, 4, 2, 1), nn.BatchNorm2d(width * 2),
            nn.ReLU(True),
            nn.Conv2d(width * 2, width * 4, 4, 2, 1), nn.BatchNorm2d(width * 4),
            nn.ReLU(True),
            nn.Conv2d(width * 4, width * 8, 4, 2, 1), nn.BatchNorm2d(width * 8),
            nn.ReLU(True),
        )
        self.to_mu = nn.Linear(width * 8 * 16, latent)
        self.to_logvar = nn.Linear(width * 8 * 16, latent)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        flattened = self.features(x).flatten(1)
        return self.to_mu(flattened), self.to_logvar(flattened)


class Decoder(nn.Module):
    """Defect 1: a sigmoid tail in front of a logits reconstruction loss."""

    def __init__(self, latent: int = LATENT, width: int = 32) -> None:
        super().__init__()
        self.project = nn.Linear(latent, width * 8 * 16)
        self.width = width
        self.net = nn.Sequential(
            nn.ConvTranspose2d(width * 8, width * 4, 4, 2, 1),
            nn.BatchNorm2d(width * 4), nn.ReLU(True),
            nn.ConvTranspose2d(width * 4, width * 2, 4, 2, 1),
            nn.BatchNorm2d(width * 2), nn.ReLU(True),
            nn.ConvTranspose2d(width * 2, width, 4, 2, 1),
            nn.BatchNorm2d(width), nn.ReLU(True),
            nn.ConvTranspose2d(width, 3, 4, 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        seed = self.project(z).view(-1, self.width * 8, 4, 4)
        return self.net(seed)


class VAE(nn.Module):
    """encoder -> reparameterise -> decoder."""

    def __init__(self, latent: int = LATENT) -> None:
        super().__init__()
        self.encoder = Encoder(latent=latent)
        self.decoder = Decoder(latent=latent)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        std = torch.exp(0.5 * logvar)
        epsilon = torch.randn_like(std)
        return mu + epsilon * std

    def forward(self, x: torch.Tensor):
        mu, logvar = self.encoder(x)
        z = self.reparameterize(mu, logvar)
        return self.decoder(z), mu, logvar


def elbo(logits: torch.Tensor, target: torch.Tensor, mu: torch.Tensor,
         logvar: torch.Tensor, kl_weight: float = KL_WEIGHT) -> torch.Tensor:
    """Defect 2: the KL term is subtracted instead of added."""
    reconstruction = F.binary_cross_entropy_with_logits(logits, target,
                                                        reduction="sum")
    kl = -0.5 * torch.sum(1.0 + logvar - mu.pow(2) - logvar.exp())
    return (reconstruction - kl_weight * kl) / target.size(0)


def build_loader() -> DataLoader:
    """Defect 6: shuffle=False."""
    pipeline = transforms.Compose([
        transforms.CenterCrop(148),
        transforms.Resize(64),
        transforms.ToTensor(),
    ])
    dataset = CelebA(root=DATA_ROOT, split="train", download=False,
                     transform=pipeline)
    train_loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False,
                              num_workers=WORKERS, pin_memory=True, drop_last=True)
    return train_loader


def train() -> nn.Module:
    seed_everything()
    device = pick_device()
    loader = build_loader()

    model = VAE().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    running = 0.0
    for epoch in range(EPOCHS):
        model.train()
        batches = 0
        for images, _labels in loader:
            images = images.to(device, non_blocking=True)
            logits, mu, logvar = model(images)
            loss = elbo(logits, images, mu, logvar)
            loss.backward()
            optimizer.step()
            running += loss
            batches += 1
        print("epoch %d elbo %.2f" % (epoch, float(running) / max(batches, 1)))
        sample(model, device, epoch)
        torch.save(model, "vae.pt")
    return model


def sample(model: nn.Module, device: torch.device, epoch: int) -> str:
    """Defect 5: no eval(), no no_grad()."""
    z = torch.randn(64, LATENT, device=device)
    images = model.decoder(z)
    path = "samples/vae_%03d.png" % epoch
    save_image(images, path, nrow=8)
    return path


if __name__ == "__main__":
    train()
