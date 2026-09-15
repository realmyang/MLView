"""A trainer written the way production infra code is actually written.

Four things here are ordinary in a real repository and awkward for a static
reader, and all four are deliberate:

* **optional dependencies** — `apex`, `wandb` and `bitsandbytes` are imported
  inside `try: / except ImportError:` and every use is guarded by the `is not
  None` flag the import set;
* **`TYPE_CHECKING`-only imports** — `DataLoader` and `Optimizer` are imported
  for annotations alone and do not exist at runtime;
* **a function-local import** — `torch.backends.cudnn` is imported inside
  `configure_backend()`, not at module scope;
* **an `importlib` dispatch** — the architecture name comes from the CLI and
  `importlib.import_module` + `getattr` turn it into a class.

MLView should say what it cannot read (the `getattr` dispatch is a genuine
dynamic construct and the coverage chip is the honest answer) and should still
draw the loop, which is entirely static. There is no defect in this file: the
loader shuffles, the eval loader does not, the step order is right, the loss is
accumulated as a float, `validate()` switches to eval under `no_grad`, and
every source of randomness is seeded.
"""
from __future__ import annotations

import argparse
import importlib
import random
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from torch.optim import Optimizer
    from torch.utils.data import DataLoader as TypedLoader

try:  # optional: NVIDIA apex, absent on CPU-only machines
    from apex import amp as apex_amp
except ImportError:  # pragma: no cover - the common path
    apex_amp = None

try:  # optional: experiment tracking
    import wandb
except ImportError:  # pragma: no cover
    wandb = None

try:  # optional: 8-bit optimizers
    import bitsandbytes as bnb
except ImportError:  # pragma: no cover
    bnb = None

ARCH_MODULE = "architectures"


def configure_backend(deterministic: bool) -> None:
    """A function-local import, which is how backend flags are usually set."""
    import torch.backends.cudnn as cudnn

    cudnn.benchmark = not deterministic
    cudnn.deterministic = deterministic


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_model(name: str, features: int, classes: int) -> nn.Module:
    """The dynamic half: the class comes out of a module by name."""
    module = importlib.import_module(ARCH_MODULE)
    factory = getattr(module, name)
    return factory(features=features, classes=classes)


def build_optimizer(model: nn.Module, lr: float, eight_bit: bool):
    if eight_bit and bnb is not None:
        return bnb.optim.AdamW8bit(model.parameters(), lr=lr)
    return torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)


def build_loaders(batch_size: int):
    features = torch.randn(6000, 48)
    labels = torch.randint(0, 6, (6000,))
    train_set = TensorDataset(features[:4800], labels[:4800])
    val_set = TensorDataset(features[4800:], labels[4800:])
    generator = torch.Generator().manual_seed(99)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              generator=generator, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    return train_loader, val_loader


def log_metrics(step: int, payload: dict) -> None:
    """Guarded optional dependency - the flag is checked, not the import."""
    if wandb is None:
        print("step %d %s" % (step, payload))
        return
    wandb.log(payload, step=step)


def train_one_epoch(model: nn.Module, loader: "TypedLoader",
                    optimizer: "Optimizer", criterion: nn.Module,
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
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


@torch.no_grad()
def validate(model: nn.Module, loader: "TypedLoader",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="conditional-import trainer")
    parser.add_argument("--arch", default="WideMLP")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=99)
    parser.add_argument("--eight-bit", action="store_true")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("checkpoints/cond"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    configure_backend(args.deterministic)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader, val_loader = build_loaders(args.batch_size)

    model = build_model(args.arch, features=48, classes=6).to(device)
    optimizer = build_optimizer(model, args.lr, args.eight_bit)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)

    scaled: Optional[object] = None
    if apex_amp is not None and device.type == "cuda":
        model, optimizer = apex_amp.initialize(model, optimizer, opt_level="O1")
        scaled = apex_amp

    best = 0.0
    args.out.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        loss = train_one_epoch(model, train_loader, optimizer, criterion, device)
        accuracy = validate(model, val_loader, device)
        log_metrics(epoch, {"loss": loss, "accuracy": accuracy,
                            "amp": scaled is not None})
        if accuracy > best:
            best = accuracy
            torch.save({"model": model.state_dict(), "epoch": epoch},
                       args.out / "best.pt")


if __name__ == "__main__":
    main()
