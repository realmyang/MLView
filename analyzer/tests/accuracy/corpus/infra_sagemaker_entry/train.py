"""A SageMaker script-mode entrypoint: training and serving in one module.

SageMaker runs this file twice in two different lifetimes. During training it
executes `__main__`, which reads the `SM_*` environment variables the platform
exports and calls `train()`. During inference it *imports* the same module and
calls four hook functions by name — `model_fn`, `input_fn`, `predict_fn`,
`output_fn` — none of which has a call site anywhere in the repository.

That is the shape this program exists to test. The serving half runs the model
in a loop-free function, under `torch.no_grad()` and after `model.eval()`; it
is not a training loop and must never be drawn as one, and the training half
must still be found even though its only entrypoint is an `if __name__` block
that reads its configuration out of `os.environ`.

One planted defect: `model_fn` at line 143 calls `torch.load(...)` with neither
`weights_only=` nor `map_location=`, which is MLV803 — and is a live problem on
a SageMaker inference container, because the training instance had a GPU and the
serving instance usually does not.

Everything else is correct: the loader shuffles, the eval loader does not, the
step order is right, the loss is accumulated as a float, `validate()` switches
to eval under `no_grad`, and the seed comes from the hyperparameters.
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

CONTENT_TYPE_JSON = "application/json"


class FraudNet(nn.Module):
    def __init__(self, features: int = 30, width: int = 96, classes: int = 2):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(features, width),
            nn.BatchNorm1d(width),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(width, width // 2),
            nn.ReLU(),
        )
        self.head = nn.Linear(width // 2, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_channel(channel_dir: str) -> TensorDataset:
    """SageMaker mounts each input channel as a directory of .npy shards."""
    root = Path(channel_dir)
    features = np.concatenate([np.load(p) for p in sorted(root.glob("x_*.npy"))])
    labels = np.concatenate([np.load(p) for p in sorted(root.glob("y_*.npy"))])
    return TensorDataset(torch.from_numpy(features.astype("float32")),
                         torch.from_numpy(labels.astype("int64")))


def train_one_epoch(model: nn.Module, loader: DataLoader, optimizer, criterion,
                    device: torch.device) -> float:
    model.train()
    running = 0.0
    for features, labels in loader:
        features = features.to(device)
        labels = labels.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


@torch.no_grad()
def validate(model: nn.Module, loader: DataLoader,
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


def train(args: argparse.Namespace) -> None:
    seed_everything(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_set = load_channel(args.train_channel)
    val_set = load_channel(args.validation_channel)
    train_loader = DataLoader(train_set, batch_size=args.batch_size,
                              shuffle=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False)

    model = FraudNet(features=args.features).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=args.epochs)

    best = 0.0
    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        loss = train_one_epoch(model, train_loader, optimizer, criterion, device)
        accuracy = validate(model, val_loader, device)
        scheduler.step()
        print("epoch %d loss %.4f accuracy %.4f" % (epoch, loss, accuracy))
        if accuracy > best:
            best = accuracy
            torch.save(model.state_dict(), model_dir / "model.pt")
            (model_dir / "config.json").write_text(
                json.dumps({"features": args.features, "classes": 2}))


# ------------------------------------------------------------- inference
# SageMaker imports this module and calls the four hooks below by name. None of
# them has a call site here, and none of them trains anything.
def model_fn(model_dir: str) -> nn.Module:
    config = json.loads((Path(model_dir) / "config.json").read_text())
    model = FraudNet(features=config["features"], classes=config["classes"])
    state = torch.load(os.path.join(model_dir, "model.pt"))
    model.load_state_dict(state)
    model.eval()
    return model


def input_fn(request_body: str, content_type: str = CONTENT_TYPE_JSON):
    if content_type != CONTENT_TYPE_JSON:
        raise ValueError("unsupported content type %s" % content_type)
    payload = json.loads(request_body)
    return torch.tensor(payload["instances"], dtype=torch.float32)


@torch.no_grad()
def predict_fn(inputs: torch.Tensor, model: nn.Module):
    model.eval()
    logits = model(inputs)
    return torch.softmax(logits, dim=1)


def output_fn(prediction, accept: str = CONTENT_TYPE_JSON) -> str:
    if accept != CONTENT_TYPE_JSON:
        raise ValueError("unsupported accept type %s" % accept)
    return json.dumps({"probabilities": prediction.tolist()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SageMaker fraud trainer")
    parser.add_argument("--epochs", type=int,
                        default=int(os.environ.get("SM_HP_EPOCHS", "15")))
    parser.add_argument("--batch-size", type=int,
                        default=int(os.environ.get("SM_HP_BATCH_SIZE", "256")))
    parser.add_argument("--lr", type=float,
                        default=float(os.environ.get("SM_HP_LR", "0.001")))
    parser.add_argument("--features", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--model-dir", dest="model_dir",
                        default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
    parser.add_argument("--train-channel", dest="train_channel",
                        default=os.environ.get("SM_CHANNEL_TRAIN",
                                               "/opt/ml/input/data/train"))
    parser.add_argument("--validation-channel", dest="validation_channel",
                        default=os.environ.get("SM_CHANNEL_VALIDATION",
                                               "/opt/ml/input/data/validation"))
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
