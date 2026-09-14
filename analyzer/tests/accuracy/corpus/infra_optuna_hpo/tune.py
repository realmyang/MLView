"""Optuna hyper-parameter search over a small PyTorch model.

The shape this program exists to test is the **nested loop**: a study loop
outside, an epoch loop inside it, a batch loop inside that, and a second,
completely separate training run after the search is over. Two training loops
and two evaluation loops live in one file and only one of each belongs to the
final model.

Everything is correct and deliberately so:

* the split happens once, in `load_split()`, before any transformer is fitted;
* `StandardScaler` is fitted on `x_train` alone and merely `transform`s the
  validation and test matrices;
* the search selects on **validation** accuracy and never touches `x_test`
  until `final_fit()` has finished;
* the training loaders shuffle, the evaluation loaders do not;
* `evaluate()` calls `model.eval()` and runs under `torch.no_grad()`;
* every random source is seeded, including Optuna's sampler;
* the checkpoint is a `state_dict`, loaded back with `weights_only=True`.

Any finding in this file is a false positive.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
import optuna
import torch
import torch.nn as nn
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

SEED = 17
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class TunableMLP(nn.Module):
    def __init__(self, features: int, width: int, depth: int, dropout: float,
                 classes: int) -> None:
        super().__init__()
        blocks = []
        size = features
        for _ in range(depth):
            blocks.append(nn.Linear(size, width))
            blocks.append(nn.GELU())
            blocks.append(nn.Dropout(dropout))
            size = width
        self.body = nn.Sequential(*blocks)
        self.head = nn.Linear(size, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


def load_split(seed: int):
    """Split first, then fit the scaler on the training rows only."""
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(6000, 24)).astype("float32")
    labels = rng.integers(0, 3, size=(6000,)).astype("int64")

    x_train, x_hold, y_train, y_hold = train_test_split(
        features, labels, test_size=0.3, random_state=seed, stratify=labels)
    x_val, x_test, y_val, y_test = train_test_split(
        x_hold, y_hold, test_size=0.5, random_state=seed, stratify=y_hold)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(x_train)
    x_val = scaler.transform(x_val)
    x_test = scaler.transform(x_test)
    return (x_train, y_train), (x_val, y_val), (x_test, y_test)


def as_dataset(x, y) -> TensorDataset:
    return TensorDataset(torch.from_numpy(np.asarray(x, dtype="float32")),
                         torch.from_numpy(np.asarray(y, dtype="int64")))


def loaders(train_set, eval_set, batch_size: int):
    generator = torch.Generator().manual_seed(SEED)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              generator=generator, drop_last=True)
    eval_loader = DataLoader(eval_set, batch_size=batch_size, shuffle=False)
    return train_loader, eval_loader


def train_one_epoch(model, loader, optimizer, criterion) -> float:
    model.train()
    running = 0.0
    for features, labels in loader:
        features = features.to(DEVICE)
        labels = labels.to(DEVICE)
        optimizer.zero_grad(set_to_none=True)
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


@torch.no_grad()
def evaluate(model, loader) -> float:
    model.eval()
    correct = 0
    seen = 0
    for features, labels in loader:
        features = features.to(DEVICE)
        labels = labels.to(DEVICE)
        predicted = model(features).argmax(dim=1)
        correct += (predicted == labels).sum().item()
        seen += labels.numel()
    model.train()
    return correct / max(seen, 1)


def build_objective(train_set, val_set):
    """Closure Optuna calls once per trial; each trial is a fresh model."""

    def objective(trial: optuna.Trial) -> float:
        width = trial.suggest_int("width", 32, 256, step=32)
        depth = trial.suggest_int("depth", 1, 4)
        dropout = trial.suggest_float("dropout", 0.0, 0.5)
        lr = trial.suggest_float("lr", 1e-4, 1e-2, log=True)
        batch_size = trial.suggest_categorical("batch_size", [32, 64, 128])

        train_loader, val_loader = loaders(train_set, val_set, batch_size)
        model = TunableMLP(features=24, width=width, depth=depth,
                           dropout=dropout, classes=3).to(DEVICE)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
        criterion = nn.CrossEntropyLoss()

        accuracy = 0.0
        for epoch in range(8):
            train_one_epoch(model, train_loader, optimizer, criterion)
            accuracy = evaluate(model, val_loader)
            trial.report(accuracy, epoch)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return accuracy

    return objective


def final_fit(best_params, train_set, val_set, test_set, out: Path) -> float:
    """Retrain on the search's winner and score the test split exactly once."""
    train_loader, test_loader = loaders(train_set, test_set,
                                        best_params["batch_size"])
    _unused, val_loader = loaders(train_set, val_set, best_params["batch_size"])
    model = TunableMLP(features=24, width=best_params["width"],
                       depth=best_params["depth"],
                       dropout=best_params["dropout"], classes=3).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=best_params["lr"])
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=20)

    best = 0.0
    out.mkdir(parents=True, exist_ok=True)
    for _epoch in range(20):
        train_one_epoch(model, train_loader, optimizer, criterion)
        validation = evaluate(model, val_loader)
        scheduler.step()
        if validation > best:
            best = validation
            torch.save(model.state_dict(), out / "best.pt")

    model.load_state_dict(torch.load(out / "best.pt", weights_only=True))
    return evaluate(model, test_loader)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optuna search")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("artifacts/optuna"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(SEED)

    (x_train, y_train), (x_val, y_val), (x_test, y_test) = load_split(SEED)
    train_set = as_dataset(x_train, y_train)
    val_set = as_dataset(x_val, y_val)
    test_set = as_dataset(x_test, y_test)

    study = optuna.create_study(
        direction="maximize",
        sampler=TPESampler(seed=SEED),
        pruner=MedianPruner(n_startup_trials=5, n_warmup_steps=2))
    study.optimize(build_objective(train_set, val_set), n_trials=args.trials)

    print("best value %.4f" % study.best_value)
    accuracy = final_fit(study.best_params, train_set, val_set, test_set,
                         args.out)
    print("test accuracy %.4f" % accuracy)


if __name__ == "__main__":
    main()
