"""The model and the loop. Everything numeric arrives on the `TrainConfig`.

The two planted defects are one hop away from this file: `cfg.shuffle` at line
63 and `cfg.num_workers` at lines 64 and 66 are dataclass field defaults in
`config.py`, and the dataclass is what makes them knowable. Everything else
here is correct — the step order, the float accumulation, the eval switch, the
`no_grad` and the `state_dict` checkpoint.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from .config import TrainConfig


class TabularNet(nn.Module):
    def __init__(self, features: int, width: int, dropout: float,
                 classes: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, width),
            nn.BatchNorm1d(width),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width, width // 2),
            nn.GELU(),
        )
        self.head = nn.Linear(width // 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_datasets(cfg: TrainConfig):
    rows = 9000
    rng = np.random.default_rng(cfg.seed)
    x = rng.normal(size=(rows, cfg.features)).astype("float32")
    y = rng.integers(0, cfg.classes, size=(rows,)).astype("int64")
    cut = int(rows * 0.8)
    train_set = TensorDataset(torch.from_numpy(x[:cut]),
                              torch.from_numpy(y[:cut]))
    val_set = TensorDataset(torch.from_numpy(x[cut:]),
                            torch.from_numpy(y[cut:]))
    return train_set, val_set


def build_loaders(cfg: TrainConfig):
    train_set, val_set = build_datasets(cfg)
    train_loader = DataLoader(train_set, batch_size=cfg.batch_size,
                              shuffle=cfg.shuffle,
                              num_workers=cfg.num_workers, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=cfg.batch_size,
                            shuffle=False, num_workers=cfg.num_workers)
    return train_loader, val_loader


def build_model(cfg: TrainConfig) -> nn.Module:
    return TabularNet(features=cfg.features, width=cfg.width,
                      dropout=cfg.dropout, classes=cfg.classes)


@torch.no_grad()
def evaluate(model: nn.Module, loader: DataLoader,
             device: torch.device) -> float:
    model.eval()
    correct = 0
    seen = 0
    for features, labels in loader:
        features = features.to(device)
        labels = labels.to(device)
        predicted = model(features).argmax(dim=1)
        correct += (predicted == labels).sum().item()
        seen += labels.numel()
    model.train()
    return correct / max(seen, 1)


def run_training(cfg: TrainConfig) -> float:
    seed_everything(cfg.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_loader, val_loader = build_loaders(cfg)
    model = build_model(cfg).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr,
                                  weight_decay=cfg.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=cfg.epochs)

    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    best = 0.0
    for epoch in range(cfg.epochs):
        model.train()
        running = 0.0
        for features, labels in train_loader:
            features = features.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running += loss.item()
        scheduler.step()

        accuracy = evaluate(model, val_loader, device)
        print("epoch %d loss %.4f acc %.4f"
              % (epoch, running / max(len(train_loader), 1), accuracy))
        if accuracy > best:
            best = accuracy
            torch.save(model.state_dict(), out / "best.pt")
    return best


def run_evaluation(cfg: TrainConfig, checkpoint: Path) -> float:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _train_loader, val_loader = build_loaders(cfg)
    model = build_model(cfg).to(device)
    model.load_state_dict(torch.load(checkpoint, weights_only=True))
    return evaluate(model, val_loader, device)
