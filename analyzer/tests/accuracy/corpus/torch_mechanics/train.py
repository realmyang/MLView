"""Mixed-precision training with clipping and a cosine schedule.

Planted defects: the device is named outright with no availability check; the
backward runs outside scaler.scale(), so half-precision gradients underflow;
the clip runs after the optimizer step, so it clips gradients that have already
been applied; the cosine schedule is stepped once per batch rather than once per
epoch; and the whole module is pickled instead of its state_dict.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast

from data import build_loaders

EPOCHS = 40
SEED = 5


class Net(nn.Module):
    def __init__(self, classes: int = 10, width: int = 64) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(3, width, kernel_size=3, padding=1),
            nn.BatchNorm2d(width),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
        )
        self.head = nn.Linear(width, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


def train():
    torch.manual_seed(SEED)
    train_loader, _test_loader = build_loaders()

    device = torch.device("cuda")
    model = Net().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1, momentum=0.9)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    scaler = GradScaler("cuda")

    model.train()
    for epoch in range(EPOCHS):
        for images, labels in train_loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            with autocast("cuda"):
                loss = criterion(model(images), labels)
            loss.backward()
            scaler.step(optimizer)
            scaler.update()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scheduler.step()

    torch.save(model, "runs/cifar.pt")
    return model
