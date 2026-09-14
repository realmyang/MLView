"""A Lightning **Fabric** training script — the hand-written loop, accelerated.

Fabric is the half-way house between a raw PyTorch loop and `pl.Trainer`: the
user keeps every statement of the loop and Fabric owns device placement,
precision, the distributed wrapper and the backward call. That makes it the
sharpest precision trap in the framework family, because the loop *looks*
hand-written but four of the things an absence rule looks for are gone:

* `fabric.setup(model, optimizer)` moves the model — there is no `.to(device)`;
* `fabric.setup_dataloaders(...)` installs the distributed sampler and moves
  every batch — there is no `x.to(device)` in the loop;
* `fabric.backward(loss)` replaces `loss.backward()`;
* `fabric.seed_everything(...)` is the seeding call.

Everything a reviewer would check is done: the training loader shuffles, the
eval loaders do not, `model.eval()` guards the validation pass — Fabric does
**not** switch train/eval mode for you, so that line is load-bearing — the
validation pass runs under `torch.no_grad()`, the loss is accumulated as a
Python float, only rank zero writes a checkpoint, and the checkpoint holds a
`state_dict` rather than the module object.

Nothing in this file is a defect. Any high-severity finding here is a false
positive.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch
import torch.nn as nn
from lightning.fabric import Fabric
from torch.utils.data import DataLoader, TensorDataset


class TokenClassifier(nn.Module):
    """A small encoder/head pair with dropout, so MLV301 has something to judge."""

    def __init__(self, vocab: int = 512, width: int = 96, classes: int = 5) -> None:
        super().__init__()
        self.embed = nn.Embedding(vocab, width)
        self.encoder = nn.Sequential(
            nn.Linear(width, width * 2),
            nn.GELU(),
            nn.Dropout(0.15),
            nn.Linear(width * 2, width),
            nn.LayerNorm(width),
        )
        self.head = nn.Linear(width, classes)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        pooled = self.embed(tokens).mean(dim=1)
        return self.head(self.encoder(pooled))


def build_datasets(rows: int = 4096, length: int = 24):
    tokens = torch.randint(0, 512, (rows, length))
    labels = torch.randint(0, 5, (rows,))
    cut = int(rows * 0.8)
    train_set = TensorDataset(tokens[:cut], labels[:cut])
    val_set = TensorDataset(tokens[cut:], labels[cut:])
    return train_set, val_set


def build_loaders(train_set, val_set, batch_size: int, workers: int):
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              num_workers=workers, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False,
                            num_workers=workers)
    return train_loader, val_loader


def train_one_epoch(fabric: Fabric, model, loader, optimizer, criterion) -> float:
    model.train()
    running = 0.0
    seen = 0
    for tokens, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        logits = model(tokens)
        loss = criterion(logits, labels)
        fabric.backward(loss)
        fabric.clip_gradients(model, optimizer, max_norm=1.0)
        optimizer.step()
        running += loss.item() * labels.numel()
        seen += labels.numel()
    return running / max(seen, 1)


@torch.no_grad()
def validate(model, loader) -> float:
    model.eval()
    correct = 0
    seen = 0
    for tokens, labels in loader:
        preds = model(tokens).argmax(dim=1)
        correct += (preds == labels).sum().item()
        seen += labels.numel()
    model.train()
    return correct / max(seen, 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fabric token classifier")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--devices", type=int, default=2)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--out", type=Path, default=Path("checkpoints/fabric"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    fabric = Fabric(accelerator="auto", devices=args.devices,
                    strategy="ddp", precision="bf16-mixed")
    fabric.launch()
    fabric.seed_everything(args.seed)

    train_set, val_set = build_datasets()
    train_loader, val_loader = build_loaders(train_set, val_set,
                                             args.batch_size, args.workers)

    model = TokenClassifier()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=0.01)
    criterion = nn.CrossEntropyLoss()

    model, optimizer = fabric.setup(model, optimizer)
    train_loader, val_loader = fabric.setup_dataloaders(train_loader, val_loader)

    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                          T_max=args.epochs)

    best = 0.0
    for epoch in range(args.epochs):
        loss = train_one_epoch(fabric, model, train_loader, optimizer, criterion)
        accuracy = validate(model, val_loader)
        scheduler.step()
        fabric.print("epoch %d loss %.4f acc %.4f" % (epoch, loss, accuracy))
        if accuracy > best and fabric.global_rank == 0:
            best = accuracy
            args.out.mkdir(parents=True, exist_ok=True)
            fabric.save(str(args.out / "best.ckpt"),
                        {"model": model.state_dict(),
                         "optimizer": optimizer.state_dict(),
                         "epoch": epoch})


if __name__ == "__main__":
    main()
