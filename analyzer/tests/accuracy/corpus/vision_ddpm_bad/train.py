"""DDPM training (defective twin).

Defect 3: nothing in the project seeds anything, so the timestep draw, the
noise draw and the initialisation all move between runs.
Defect 4: the training step never zeroes the gradients.
Defect 5: the epoch loss is accumulated as a live tensor.
Defect 6: the training loader does not shuffle, so every epoch sees CIFAR-10
in class order - ten thousand airplanes, then ten thousand cars.
Defect 7 (no rule covers it yet): the EMA is updated *before* the optimiser
step, so the shadow weights track the previous iteration for ever.
Defect 8: the whole module is pickled instead of its state dict.
"""

from __future__ import annotations

import copy

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import CIFAR10
from torchvision.utils import save_image

from diffusion import GaussianDiffusion

DATA_ROOT = "data/cifar10"
EPOCHS = 200
BATCH_SIZE = 128
WORKERS = 8
LR = 2e-4
EMA_DECAY = 0.9999
TIMESTEPS = 1000


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class TimeEmbedding(nn.Module):
    """Sinusoidal timestep features, projected through two linears."""

    def __init__(self, dim: int = 128) -> None:
        super().__init__()
        self.dim = dim
        self.project = nn.Sequential(nn.Linear(dim, dim * 4), nn.SiLU(),
                                     nn.Linear(dim * 4, dim * 4))

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        half = self.dim // 2
        frequencies = torch.exp(
            -torch.arange(half, device=t.device) * (9.21 / max(half - 1, 1)))
        angles = t.float().unsqueeze(1) * frequencies.unsqueeze(0)
        embedding = torch.cat([angles.sin(), angles.cos()], dim=1)
        return self.project(embedding)


class ResidualBlock(nn.Module):
    """GroupNorm - SiLU - conv, twice, with the time embedding added."""

    def __init__(self, cin: int, cout: int, time_dim: int) -> None:
        super().__init__()
        self.norm1 = nn.GroupNorm(8, cin)
        self.conv1 = nn.Conv2d(cin, cout, 3, padding=1)
        self.time = nn.Linear(time_dim, cout)
        self.norm2 = nn.GroupNorm(8, cout)
        self.dropout = nn.Dropout(0.1)
        self.conv2 = nn.Conv2d(cout, cout, 3, padding=1)
        self.skip = nn.Conv2d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(self, x: torch.Tensor, t_emb: torch.Tensor) -> torch.Tensor:
        h = self.conv1(F.silu(self.norm1(x)))
        h = h + self.time(t_emb).unsqueeze(-1).unsqueeze(-1)
        h = self.conv2(self.dropout(F.silu(self.norm2(h))))
        return h + self.skip(x)


class EpsilonUNet(nn.Module):
    """A three-level UNet that predicts the noise in x_t."""

    def __init__(self, channels: int = 3, base: int = 64) -> None:
        super().__init__()
        self.time_embedding = TimeEmbedding(base * 2)
        time_dim = base * 8
        self.stem = nn.Conv2d(channels, base, 3, padding=1)
        self.down = nn.ModuleList([
            ResidualBlock(base, base, time_dim),
            ResidualBlock(base, base * 2, time_dim),
            ResidualBlock(base * 2, base * 4, time_dim),
        ])
        self.pool = nn.AvgPool2d(2)
        self.middle = ResidualBlock(base * 4, base * 4, time_dim)
        self.up = nn.ModuleList([
            ResidualBlock(base * 4, base * 2, time_dim),
            ResidualBlock(base * 2, base, time_dim),
            ResidualBlock(base, base, time_dim),
        ])
        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")
        self.head = nn.Conv2d(base, channels, 3, padding=1)

    def forward(self, x: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        t_emb = self.time_embedding(t)
        h = self.stem(x)
        for index, block in enumerate(self.down):
            h = block(h, t_emb)
            if index < len(self.down) - 1:
                h = self.pool(h)
        h = self.middle(h, t_emb)
        for index, block in enumerate(self.up):
            h = block(h, t_emb)
            if index < len(self.up) - 1:
                h = self.upsample(h)
        return self.head(h)


class Ema:
    """A shadow copy of the weights."""

    def __init__(self, model: nn.Module, decay: float = EMA_DECAY) -> None:
        self.decay = decay
        self.shadow = copy.deepcopy(model).eval()
        for parameter in self.shadow.parameters():
            parameter.requires_grad_(False)

    @torch.no_grad()
    def update(self, model: nn.Module) -> None:
        target = dict(self.shadow.named_parameters())
        for name, value in model.named_parameters():
            target[name].mul_(self.decay).add_(value.detach(), alpha=1 - self.decay)


def build_loader() -> DataLoader:
    """Defect 6: shuffle=False on a class-ordered dataset."""
    pipeline = transforms.Compose([
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])
    dataset = CIFAR10(root=DATA_ROOT, train=True, download=False, transform=pipeline)
    return DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False,
                      num_workers=WORKERS, pin_memory=True, drop_last=True)


def train() -> nn.Module:
    device = pick_device()
    loader = build_loader()

    model = EpsilonUNet().to(device)
    diffusion = GaussianDiffusion(timesteps=TIMESTEPS).to(device)
    ema = Ema(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.0)

    for epoch in range(EPOCHS):
        model.train()
        running = 0.0
        batches = 0
        for images, _labels in loader:
            images = images.to(device, non_blocking=True)
            t = diffusion.sample_timesteps(images.size(0), device)
            noise = torch.randn_like(images)
            noisy = diffusion.q_sample(images, t, noise)

            predicted = model(noisy, t)
            loss = F.mse_loss(predicted, noise)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            ema.update(model)
            optimizer.step()

            running += loss
            batches += 1

        print("epoch %d loss %.5f" % (epoch, float(running) / max(batches, 1)))
        if epoch % 10 == 0:
            grid = diffusion.p_sample_loop(ema.shadow, (16, 3, 32, 32), device)
            save_image(grid * 0.5 + 0.5, "samples/ddpm_%03d.png" % epoch, nrow=4)
            torch.save(model, "ddpm.pt")
    return model


if __name__ == "__main__":
    train()
