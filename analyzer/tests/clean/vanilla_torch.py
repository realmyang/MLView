"""The textbook PyTorch loop, written correctly.

Part of the precision corpus: `tests/rules/test_precision.py` asserts that the
whole corpus produces **no high-severity finding at all**. Nothing here is ever
executed - MLView reads it statically and torch is not installed.
"""
from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset, random_split

SEED = 1337
BATCH_SIZE = 64
EPOCHS = 5


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class SmallNet(nn.Module):
    def __init__(self, features: int = 64, classes: int = 10) -> None:
        super().__init__()
        self.blocks = nn.ModuleList([nn.Linear(features, features) for _ in range(2)])
        self.norm = nn.BatchNorm1d(features)
        self.drop = nn.Dropout(0.3)
        self.head = nn.Linear(features, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for block in self.blocks:
            x = F.relu(block(x))
        return self.head(self.drop(self.norm(x)))


def build_loaders(dataset: TensorDataset):
    generator = torch.Generator().manual_seed(SEED)
    train_ds, val_ds = random_split(dataset, [45000, 5000], generator=generator)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=256, shuffle=False)
    return train_loader, val_loader


def train_one_epoch(model, loader, criterion, optimizer, device) -> float:
    model.train()
    running_loss = 0.0
    for features, labels in loader:
        features = features.to(device, non_blocking=True)
        labels = labels.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        running_loss += loss.item()
    return running_loss / max(len(loader), 1)


@torch.no_grad()
def evaluate(model, loader, device) -> float:
    model.eval()
    correct = 0
    total = 0
    for features, labels in loader:
        features = features.to(device)
        labels = labels.to(device)
        preds = model(features).argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)
    model.train()
    return correct / max(total, 1)


def main(dataset: TensorDataset) -> nn.Module:
    set_seed()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SmallNet().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    train_loader, val_loader = build_loaders(dataset)

    for epoch in range(EPOCHS):
        train_one_epoch(model, train_loader, criterion, optimizer, device)
        evaluate(model, val_loader, device)
        scheduler.step()
    return model
