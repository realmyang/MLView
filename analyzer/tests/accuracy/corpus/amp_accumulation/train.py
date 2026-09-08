"""Mixed precision plus gradient accumulation, done wrong in four places.

The clean twin of this shape lives at `analyzer/tests/clean/amp_accumulation.py`;
this is the version a tired person writes at the end of the day.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset

ACCUM_STEPS = 4
DEVICE = "cuda"


class Net(nn.Module):
    def __init__(self, features: int = 64, classes: int = 10) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, 256),
            nn.ReLU(),
            nn.BatchNorm1d(256),
            nn.Dropout(0.25),
        )
        self.head = nn.Linear(256, classes)

    def forward(self, x):
        return self.head(self.body(x))


def make_loaders(features, labels, batch_size: int = 32):
    dataset = TensorDataset(features, labels)
    train_set, val_set = torch.utils.data.random_split(dataset, [0.9, 0.1])
    return (DataLoader(train_set, batch_size=batch_size, shuffle=True),
            DataLoader(val_set, batch_size=batch_size))


def train(model, loader, epochs: int = 10):
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()
    scaler = GradScaler(DEVICE)
    model.to(DEVICE)

    for epoch in range(epochs):
        running = 0.0
        for step, (features, labels) in enumerate(loader):
            features = features.to(DEVICE)
            labels = labels.to(DEVICE)
            with autocast(DEVICE):
                loss = criterion(model(features), labels) / ACCUM_STEPS
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM_STEPS == 0:
                scaler.step(optimizer)
                scaler.update()
            running += loss
        print(epoch, float(running))
    return model


def validate(model, loader):
    hits = 0
    seen = 0
    for features, labels in loader:
        logits = model(features)
        hits += (logits.argmax(dim=-1) == labels).sum().item()
        seen += labels.shape[0]
    return hits / max(seen, 1)


def main():
    features = torch.randn(4096, 64)
    labels = torch.randint(0, 10, (4096,))
    train_loader, val_loader = make_loaders(features, labels)
    model = train(Net(), train_loader)
    print(validate(model, val_loader))


if __name__ == "__main__":
    main()
