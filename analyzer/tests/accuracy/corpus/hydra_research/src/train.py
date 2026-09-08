"""The hand-written loop, driven by a Hydra-style config dict.

Planted defects: gradients are never zeroed, the epoch loss is accumulated as a
live tensor, and the validation pass neither switches to eval mode nor moves the
batch to the device the model was sent to.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from data import csv_dataset, loaders
from models import optimizer_for
from registry import build_from_cfg

CFG = {
    "model": {"name": "mlp", "args": {"features": 32, "hidden": 256}},
    "optimizer": "AdamW",
    "lr": 3e-4,
    "epochs": 40,
    "device": "cuda",
}


def train(cfg=CFG):
    train_x, test_x, train_y, test_y = csv_dataset()
    train_loader, test_loader = loaders(train_x, test_x, train_y, test_y)

    model = build_from_cfg("model", cfg["model"]).to(cfg["device"])
    optimizer = optimizer_for(model, cfg)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(cfg["epochs"]):
        total = 0.0
        for features, labels in train_loader:
            features = features.to(cfg["device"])
            labels = labels.to(cfg["device"])
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
            total += loss
        print(epoch, float(total))

    return model, test_loader


def validate(model, loader):
    hits = 0
    seen = 0
    for features, labels in loader:
        logits = model(features)
        hits += (logits.argmax(dim=-1) == labels).sum().item()
        seen += labels.shape[0]
    return hits / max(seen, 1)


def main():
    model, loader = train()
    print(validate(model, loader))


if __name__ == "__main__":
    main()
