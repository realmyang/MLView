"""Training the same forecaster, with nine mechanics wrong at once.

Planted defects, in the order they appear:

* `torch.device("cuda")` is hard-coded with no availability probe;
* the evaluation loader is built with `shuffle=True`, so predictions no longer
  line up with the hours they belong to;
* both loaders ask for four worker processes and the module has no
  `if __name__ == "__main__":` guard, which re-imports the module in every
  worker on spawn platforms;
* `optimizer.zero_grad()` is never called, so gradients accumulate across every
  batch of the run;
* the batch tensors are never moved to the device the model was moved to;
* the running loss is accumulated as a live tensor, keeping every batch's graph
  alive for the whole epoch;
* `OneCycleLR` is a per-batch schedule and is stepped once per epoch, so the
  cycle finishes in the first few epochs and the rest of the run trains at the
  floor learning rate;
* the evaluation pass never calls `model.eval()` and is not wrapped in
  `torch.no_grad()`, so dropout stays on and the graph is built for nothing;
* the whole model object is pickled and read back without `weights_only=True`.
"""
from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.optim.lr_scheduler import OneCycleLR
from torch.utils.data import DataLoader

from model import LoadForecaster
from windows import build_datasets, load_series

EPOCHS = 30
BATCH_SIZE = 64
CHECKPOINT = "artifacts/load_forecaster.pt"

device = torch.device("cuda")


def build_loaders(train_set, test_set):
    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=4)
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE, shuffle=True,
                             num_workers=4)
    return train_loader, test_loader


def train_one_epoch(model, loader, criterion, optimizer):
    model.train()
    running = 0.0
    for history, future in loader:
        prediction = model(history)
        loss = criterion(prediction, future)
        loss.backward()
        optimizer.step()
        running += loss
    return running / max(len(loader), 1)


def evaluate(model, loader, criterion):
    total = 0.0
    seen = 0
    for history, future in loader:
        prediction = model(history)
        total += criterion(prediction, future).item() * history.size(0)
        seen += history.size(0)
    return total / max(seen, 1)


def fit(csv_path: str) -> float:
    frame = load_series(csv_path)
    train_set, test_set = build_datasets(frame)
    train_loader, test_loader = build_loaders(train_set, test_set)

    model = LoadForecaster().to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-3)
    scheduler = OneCycleLR(optimizer, max_lr=3e-3, epochs=EPOCHS,
                           steps_per_epoch=len(train_loader))

    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer)
        scheduler.step()
        print("epoch %d train %.4f" % (epoch, float(train_loss)))

    torch.save(model, CHECKPOINT)
    restored = torch.load(CHECKPOINT)
    return float(evaluate(restored, test_loader, criterion))


def main(csv_path: str = "data/load_hourly.csv") -> float:
    return fit(csv_path)


print(main())
