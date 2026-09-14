"""The training script. The model, the loss and the optimizer are all strings.

`CONFIG` is a module-level dict literal, which MLView does resolve; what it
cannot resolve without reading the decorators in `plugins.py` is that
`MODELS.build({"name": "wide_resnet", ...})` produces a `WideResNet`. That gap
is the point of this program. What MLView must NOT do is invent a reading: no
leakage finding, no loss-pairing finding and no architecture claim can be made
about a class it has not identified.

The loop itself is correct and written plainly: shuffle on, no shuffle on the
eval loader, `zero_grad` -> forward -> loss -> backward -> clip -> step, the
epoch loss accumulated as a float, `evaluate()` under `model.eval()` and
`torch.no_grad()`, and the seed set before anything is built.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

import plugins  # noqa: F401  - importing is what registers the plugins
from registry import LOSSES, MODELS, OPTIMIZERS

CONFIG = {
    "seed": 808,
    "epochs": 12,
    "batch_size": 128,
    "features": 64,
    "classes": 10,
    "model": {"name": "wide_resnet", "features": 64, "width": 256,
              "classes": 10, "dropout": 0.2},
    "loss": {"name": "focal", "gamma": 2.0, "alpha": 0.25},
    "optimizer": {"name": "adamw", "lr": 0.0008, "weight_decay": 0.01},
    "out": "checkpoints/registry",
}


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_loaders(features: int, classes: int, batch_size: int):
    x = torch.randn(8000, features)
    y = torch.randint(0, classes, (8000,))
    train_set = TensorDataset(x[:6400], y[:6400])
    val_set = TensorDataset(x[6400:], y[6400:])
    generator = torch.Generator().manual_seed(CONFIG["seed"])
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              generator=generator, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    return train_loader, val_loader


def main() -> None:
    seed_everything(CONFIG["seed"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_loader, val_loader = build_loaders(CONFIG["features"],
                                             CONFIG["classes"],
                                             CONFIG["batch_size"])

    model = MODELS.build(CONFIG["model"]).to(device)
    criterion = LOSSES.build(CONFIG["loss"])
    optimizer_settings = dict(CONFIG["optimizer"])
    optimizer_name = optimizer_settings.pop("name")
    optimizer = OPTIMIZERS.get(optimizer_name)(model.parameters(),
                                               **optimizer_settings)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=CONFIG["epochs"])

    out = Path(CONFIG["out"])
    out.mkdir(parents=True, exist_ok=True)
    best = 0.0
    for epoch in range(CONFIG["epochs"]):
        model.train()
        running = 0.0
        for features, labels in train_loader:
            features = features.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running += loss.item()
        scheduler.step()

        model.eval()
        correct = 0
        seen = 0
        with torch.no_grad():
            for features, labels in val_loader:
                features = features.to(device)
                labels = labels.to(device)
                predicted = model(features).argmax(dim=1)
                correct += (predicted == labels).sum().item()
                seen += labels.numel()
        accuracy = correct / max(seen, 1)
        model.train()

        print("epoch %d loss %.4f acc %.4f"
              % (epoch, running / max(len(train_loader), 1), accuracy))
        if accuracy > best:
            best = accuracy
            torch.save(model.state_dict(), out / "best.pt")


if __name__ == "__main__":
    main()
