"""The defective twin of `infra_fabric` — same Fabric script, six real bugs.

Fabric is deliberately thinner than `pl.Trainer`: it moves tensors and owns
precision and the distributed wrapper, and it owns **nothing** about the
train/eval switch, gradient hygiene or the shape of the evaluation pass. Every
defect below is therefore a defect in Fabric code exactly as it would be in a
raw PyTorch loop, and none of them is something Fabric quietly fixes:

1. line 68 — the training loader passes no `shuffle=` and no `sampler=`, so the
   batches arrive in dataset order for every epoch (MLV110);
2. line 71 — the validation loader passes `shuffle=True`, so predictions stop
   lining up with the dataset and the confusion matrix is not reproducible
   (MLV111);
3. line 87 — `running += loss`, so every step's autograd graph is kept alive
   for the whole epoch (MLV205);
4. line 94 — `validate()` never calls `model.eval()`, so dropout stays on
   during validation and the reported accuracy is wrong. Fabric does not switch
   modes (MLV301);
5. line 94 — and it is not wrapped in `torch.no_grad()`, so the validation pass
   builds an autograd graph it never uses (MLV302);
6. line 152 — the checkpoint pickles the module object rather than its
   `state_dict`, and line 156 loads it back with no `weights_only=` (MLV803).

The split, the seeding, the optimizer order and the module construction are all
identical to the correct twin, so any finding outside the six above is a false
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
    train_loader = DataLoader(train_set, batch_size=batch_size,
                              num_workers=workers, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=True,
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
        running += loss
        seen += labels.numel()
    return float(running) / max(seen, 1)


def validate(model, loader) -> float:
    correct = 0
    seen = 0
    for tokens, labels in loader:
        preds = model(tokens).argmax(dim=1)
        correct += (preds == labels).sum().item()
        seen += labels.numel()
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
    args.out.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        loss = train_one_epoch(fabric, model, train_loader, optimizer, criterion)
        accuracy = validate(model, val_loader)
        scheduler.step()
        fabric.print("epoch %d loss %.4f acc %.4f" % (epoch, loss, accuracy))
        if accuracy > best and fabric.global_rank == 0:
            best = accuracy
            torch.save(model, args.out / "best.pt")

    restored = torch.load(args.out / "best.pt")
    fabric.print("restored %s" % type(restored).__name__)


if __name__ == "__main__":
    main()
