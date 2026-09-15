"""Training the hourly load forecaster, with every mechanic in its place.

`zero_grad` -> `backward` -> clip -> `step`, the scheduler stepped once per
epoch because it is an epoch-cadence scheduler, the running loss accumulated
through `.item()`, evaluation inside `model.eval()` and `torch.no_grad()`, and
the checkpoint written as a `state_dict` and read back with `weights_only=True`.

Windows are independent samples once they have been cut, so the *training*
loader shuffles them - the chronological guarantee lives in the cut, not in the
batch order - and the validation loader does not, so its predictions stay
aligned with the hours they belong to.
"""
from __future__ import annotations

import random

import numpy as np
import torch
from torch import nn
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

from model import LoadForecaster
from windows import build_datasets, load_series

SEED = 1234
EPOCHS = 30
BATCH_SIZE = 64
CHECKPOINT = "artifacts/load_forecaster.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(train_set, valid_set):
    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=4, pin_memory=True, drop_last=True)
    valid_loader = DataLoader(valid_set, batch_size=BATCH_SIZE, shuffle=False,
                              num_workers=4, pin_memory=True)
    return train_loader, valid_loader


def train_one_epoch(model, loader, criterion, optimizer, device) -> float:
    model.train()
    running = 0.0
    for history, future in loader:
        history = history.to(device)
        future = future.to(device)

        optimizer.zero_grad(set_to_none=True)
        prediction = model(history)
        loss = criterion(prediction, future)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        running += loss.item() * history.size(0)
    return running / max(len(loader.dataset), 1)


@torch.no_grad()
def evaluate(model, loader, criterion, device) -> dict:
    model.eval()
    total_mse = 0.0
    total_mae = 0.0
    seen = 0
    for history, future in loader:
        history = history.to(device)
        future = future.to(device)
        prediction = model(history)
        total_mse += criterion(prediction, future).item() * history.size(0)
        total_mae += torch.abs(prediction - future).mean().item() * history.size(0)
        seen += history.size(0)
    return {"mse": total_mse / max(seen, 1), "mae": total_mae / max(seen, 1)}


def fit(csv_path: str) -> dict:
    device = pick_device()
    frame = load_series(csv_path)
    train_set, valid_set, _scaler = build_datasets(frame)
    train_loader, valid_loader = build_loaders(train_set, valid_set)

    model = LoadForecaster().to(device)
    criterion = nn.SmoothL1Loss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = CosineAnnealingLR(optimizer, T_max=EPOCHS)

    best = float("inf")
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer,
                                     device)
        metrics = evaluate(model, valid_loader, criterion, device)
        scheduler.step()
        if metrics["mse"] < best:
            best = metrics["mse"]
            torch.save(model.state_dict(), CHECKPOINT)
        print("epoch %d train %.4f valid %.4f" % (epoch, train_loss, metrics["mse"]))

    model.load_state_dict(torch.load(CHECKPOINT, map_location=device,
                                     weights_only=True))
    return evaluate(model, valid_loader, criterion, device)


def main(csv_path: str = "data/load_hourly.csv") -> dict:
    seed_everything()
    return fit(csv_path)


if __name__ == "__main__":
    print(main())
