"""Ray Train: a `TorchTrainer` whose per-worker loop is an ordinary torch loop.

The project shape here is that **the training loop is never called** from this
file. `train_loop_per_worker` is handed to `TorchTrainer` as a value and Ray
calls it once per worker, in another process, with the `train_loop_config` dict
as its only argument. Everything a reader wants to know — where the data comes
from, what the loss is, whether the eval pass turns dropout off — lives inside
a function that has no call site in the workspace.

Ray also owns three things a rule usually looks for:

* `ray.train.torch.prepare_model(model)` wraps the module in DDP and moves it;
* `ray.train.torch.prepare_data_loader(loader)` installs the `DistributedSampler`
  and moves each batch;
* `ray.train.report(...)` is the checkpoint and metric channel.

The code is correct. The training loader is built with `shuffle=True` (Ray
replaces the sampler and keeps the shuffling), the eval loader is not,
`evaluate()` calls `model.eval()` inside `torch.no_grad()`, the scaler is fitted
on the training rows only and after the split, and every random source is
seeded. Any finding in this file is a false positive.
"""
from __future__ import annotations

import os
import random
from typing import Any, Dict

import numpy as np
import ray.train
import torch
import torch.nn as nn
from ray.train import CheckpointConfig, RunConfig, ScalingConfig
from ray.train.torch import TorchTrainer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

SEED = 2024


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class RiskNet(nn.Module):
    def __init__(self, features: int = 40, width: int = 128, classes: int = 2):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, width),
            nn.BatchNorm1d(width),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(width, width // 2),
            nn.ReLU(),
        )
        self.head = nn.Linear(width // 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


def build_tensors(seed: int):
    """Split first; the scaler never sees a validation row before it is fitted."""
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(20000, 40)).astype("float32")
    labels = (rng.random(20000) > 0.7).astype("int64")

    x_train, x_val, y_train, y_val = train_test_split(
        features, labels, test_size=0.2, random_state=seed, stratify=labels)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train).astype("float32")
    x_val = scaler.transform(x_val).astype("float32")

    train_set = TensorDataset(torch.from_numpy(x_train),
                              torch.from_numpy(y_train))
    val_set = TensorDataset(torch.from_numpy(x_val), torch.from_numpy(y_val))
    return train_set, val_set


@torch.no_grad()
def evaluate(model, loader) -> float:
    model.eval()
    correct = 0
    seen = 0
    for features, labels in loader:
        predicted = model(features).argmax(dim=1)
        correct += (predicted == labels).sum().item()
        seen += labels.numel()
    model.train()
    return correct / max(seen, 1)


def train_loop_per_worker(config: Dict[str, Any]) -> None:
    """Runs once per Ray worker. Ray calls it; nothing in this file does."""
    seed_everything(config["seed"])
    train_set, val_set = build_tensors(config["seed"])

    train_loader = DataLoader(train_set, batch_size=config["batch_size"],
                              shuffle=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=config["batch_size"],
                            shuffle=False)
    train_loader = ray.train.torch.prepare_data_loader(train_loader)
    val_loader = ray.train.torch.prepare_data_loader(val_loader)

    model = RiskNet(features=40, width=config["width"])
    model = ray.train.torch.prepare_model(model)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["lr"],
                                  weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=config["lr"] * 10,
        steps_per_epoch=len(train_loader), epochs=config["epochs"])

    for epoch in range(config["epochs"]):
        model.train()
        running = 0.0
        for features, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += loss.item()

        accuracy = evaluate(model, val_loader)
        ray.train.report({"loss": running / max(len(train_loader), 1),
                          "accuracy": accuracy, "epoch": epoch})


def main() -> None:
    seed_everything(SEED)
    trainer = TorchTrainer(
        train_loop_per_worker=train_loop_per_worker,
        train_loop_config={"seed": SEED, "batch_size": 256, "lr": 1e-3,
                           "width": 128, "epochs": 15},
        scaling_config=ScalingConfig(num_workers=4, use_gpu=True),
        run_config=RunConfig(
            name="risk-net",
            storage_path=os.environ.get("RAY_STORAGE", "/tmp/ray_results"),
            checkpoint_config=CheckpointConfig(num_to_keep=3,
                                               checkpoint_score_attribute="accuracy",
                                               checkpoint_score_order="max")),
    )
    result = trainer.fit()
    print("best accuracy %.4f" % result.metrics["accuracy"])


if __name__ == "__main__":
    main()
