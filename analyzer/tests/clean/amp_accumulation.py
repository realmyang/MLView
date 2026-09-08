"""Mixed precision with gradient accumulation - the classic MLV201/MLV202 trap.

`zero_grad` and `scaler.step` both sit under a modulo guard, and the step is
spelled `scaler.step(optimizer)` rather than `optimizer.step()`.
"""
from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset, random_split

SEED = 7
ACCUM_STEPS = 4
EPOCHS = 3


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class Regressor(nn.Module):
    def __init__(self, features: int = 32) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, 64),
            nn.GELU(),
            nn.Linear(64, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.body(x)


def train(dataset: TensorDataset) -> nn.Module:
    set_seed()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    generator = torch.Generator().manual_seed(SEED)
    train_ds, val_ds = random_split(dataset, [9000, 1000], generator=generator)
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=128, shuffle=False)

    model = Regressor().to(device)
    criterion = nn.MSELoss()
    optimizer = optim.SGD(model.parameters(), lr=0.05, momentum=0.9)
    scaler = GradScaler("cuda")

    model.train()
    for epoch in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        running = 0.0
        for step, (features, targets) in enumerate(train_loader):
            features = features.to(device, non_blocking=True)
            targets = targets.to(device)
            with autocast("cuda"):
                loss = criterion(model(features), targets) / ACCUM_STEPS
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM_STEPS == 0:
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            running += loss.item()
        validate(model, val_loader, criterion, device)
    return model


@torch.inference_mode()
def validate(model, loader, criterion, device) -> float:
    model.eval()
    total = 0.0
    for features, targets in loader:
        features = features.to(device)
        targets = targets.to(device)
        total += criterion(model(features), targets).item()
    model.train()
    return total / max(len(loader), 1)
