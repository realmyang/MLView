"""DCGAN training: two networks, two optimisers, one batch loop.

The ordering that looks wrong to a linter and is right to a practitioner:
`opt_d.step()` genuinely precedes `loss_g.backward()`, because they belong to
two different optimisation problems.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import ImageFolder
from torchvision.utils import save_image

from models import LATENT_DIM, Discriminator, Generator, weights_init

DATA_ROOT = "data/celeba"
SEED = 999
EPOCHS = 25
BATCH_SIZE = 128
WORKERS = 4
LR = 2e-4
BETAS = (0.5, 0.999)
SAMPLE_DIR = "samples"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loader(batch_size: int = BATCH_SIZE, workers: int = WORKERS) -> DataLoader:
    """A GAN has no held-out split: every image is a training image."""
    pipeline = transforms.Compose([
        transforms.Resize(64),
        transforms.CenterCrop(64),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    dataset = ImageFolder(DATA_ROOT, transform=pipeline)
    return DataLoader(dataset, batch_size=batch_size, shuffle=True,
                      num_workers=workers, pin_memory=True, drop_last=True)


def train(epochs: int = EPOCHS) -> tuple:
    seed_everything()
    device = pick_device()
    loader = build_loader()

    netG = Generator().to(device)
    netD = Discriminator().to(device)
    netG.apply(weights_init)
    netD.apply(weights_init)

    criterion = nn.BCEWithLogitsLoss()
    opt_g = torch.optim.Adam(netG.parameters(), lr=LR, betas=BETAS)
    opt_d = torch.optim.Adam(netD.parameters(), lr=LR, betas=BETAS)

    fixed_noise = torch.randn(64, LATENT_DIM, 1, 1, device=device)
    d_running = 0.0
    g_running = 0.0

    for epoch in range(epochs):
        for step, (real_images, _labels) in enumerate(loader):
            real_images = real_images.to(device, non_blocking=True)
            batch = real_images.size(0)
            real_labels = torch.ones(batch, device=device)
            fake_labels = torch.zeros(batch, device=device)

            # --- discriminator: maximise log D(x) + log(1 - D(G(z)))
            opt_d.zero_grad(set_to_none=True)
            logits_real = netD(real_images)
            loss_real = criterion(logits_real, real_labels)
            noise = torch.randn(batch, LATENT_DIM, 1, 1, device=device)
            fake_images = netG(noise)
            logits_fake = netD(fake_images.detach())
            loss_fake = criterion(logits_fake, fake_labels)
            loss_d = loss_real + loss_fake
            loss_d.backward()
            opt_d.step()

            # --- generator: maximise log D(G(z))
            opt_g.zero_grad(set_to_none=True)
            logits_for_g = netD(fake_images)
            loss_g = criterion(logits_for_g, real_labels)
            loss_g.backward()
            opt_g.step()

            d_running += loss_d.item()
            g_running += loss_g.item()
            if step % 100 == 0:
                print("epoch %d step %d loss_d %.4f loss_g %.4f"
                      % (epoch, step, loss_d.item(), loss_g.item()))

        sample_grid(netG, fixed_noise, epoch)
        torch.save({"netG": netG.state_dict(), "netD": netD.state_dict()},
                   "dcgan_epoch%d.pt" % epoch)

    return netG, netD


@torch.no_grad()
def sample_grid(netG, noise: torch.Tensor, epoch: int) -> str:
    """Write a fixed-noise grid so the run can be watched frame by frame."""
    netG.eval()
    images = netG(noise)
    path = "%s/epoch_%03d.png" % (SAMPLE_DIR, epoch)
    save_image(images * 0.5 + 0.5, path, nrow=8)
    netG.train()
    return path


if __name__ == "__main__":
    train()
