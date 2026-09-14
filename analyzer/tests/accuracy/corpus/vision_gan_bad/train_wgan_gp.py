"""WGAN-GP (defective twin).

Defect 8: the whole critic update was wrapped in `torch.no_grad()` by someone
chasing an out-of-memory error, so `loss_c.backward()` now runs inside a
no-grad region and raises at the first batch.
Defect 9: the gradient penalty is computed against `fake_images` that were
never detached, so the penalty's second-order graph reaches the generator.
"""

from __future__ import annotations

import random

import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import ImageFolder
from torchvision.utils import save_image

from models import LATENT_DIM, Critic, Generator

DATA_ROOT = "data/celeba"
SEED = 4242
EPOCHS = 25
BATCH_SIZE = 64
WORKERS = 4
LR = 1e-4
BETAS = (0.0, 0.9)
N_CRITIC = 5
LAMBDA_GP = 10.0


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loader(batch_size: int = BATCH_SIZE, workers: int = WORKERS) -> DataLoader:
    pipeline = transforms.Compose([
        transforms.Resize(64),
        transforms.CenterCrop(64),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    dataset = ImageFolder(DATA_ROOT, transform=pipeline)
    return DataLoader(dataset, batch_size=batch_size, shuffle=True,
                      num_workers=workers, pin_memory=True, drop_last=True)


def gradient_penalty(critic, real: torch.Tensor, fake: torch.Tensor,
                     device: torch.device) -> torch.Tensor:
    """E[(||grad C(x_hat)|| - 1)^2] on points between the two distributions."""
    batch = real.size(0)
    epsilon = torch.rand(batch, 1, 1, 1, device=device)
    interpolated = (epsilon * real + (1.0 - epsilon) * fake).requires_grad_(True)
    scores = critic(interpolated)
    gradients = torch.autograd.grad(
        outputs=scores,
        inputs=interpolated,
        grad_outputs=torch.ones_like(scores),
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
    )[0]
    gradients = gradients.view(batch, -1)
    return ((gradients.norm(2, dim=1) - 1.0) ** 2).mean()


def train(epochs: int = EPOCHS):
    seed_everything()
    device = pick_device()
    loader = build_loader()

    generator = Generator().to(device)
    critic = Critic().to(device)
    opt_g = torch.optim.Adam(generator.parameters(), lr=LR, betas=BETAS)
    opt_c = torch.optim.Adam(critic.parameters(), lr=LR, betas=BETAS)

    fixed_noise = torch.randn(64, LATENT_DIM, 1, 1, device=device)

    for epoch in range(epochs):
        for step, (real_images, _labels) in enumerate(loader):
            real_images = real_images.to(device, non_blocking=True)
            batch = real_images.size(0)

            noise = torch.randn(batch, LATENT_DIM, 1, 1, device=device)
            fake_images = generator(noise)

            with torch.no_grad():
                opt_c.zero_grad(set_to_none=True)
                critic_real = critic(real_images).mean()
                critic_fake = critic(fake_images).mean()
                penalty = gradient_penalty(critic, real_images, fake_images, device)
                loss_c = critic_fake - critic_real + LAMBDA_GP * penalty
                loss_c.backward()
                opt_c.step()

            if (step + 1) % N_CRITIC == 0:
                opt_g.zero_grad(set_to_none=True)
                loss_g = -critic(generator(noise)).mean()
                loss_g.backward()
                opt_g.step()

            if step % 200 == 0:
                print("epoch %d step %d loss_c %.4f" % (epoch, step, float(loss_c)))

        write_samples(generator, fixed_noise, epoch)
        torch.save(generator, "wgangp_epoch%d.pt" % epoch)

    return generator, critic


@torch.no_grad()
def write_samples(generator, noise: torch.Tensor, epoch: int) -> str:
    generator.eval()
    images = generator(noise)
    path = "samples/wgangp_%03d.png" % epoch
    save_image(images * 0.5 + 0.5, path, nrow=8)
    generator.train()
    return path


if __name__ == "__main__":
    train()
