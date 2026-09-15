"""The monorepo's training entrypoint (`vision-train`).

Correct on purpose. It is here to give the workspace a real train/eval loop
beside the tests and the notebooks, so the repository shape — a `tests/`
folder, a `notebooks/` folder and one real pipeline — is what MLView sees.
"""
from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn

from libs.vision import VisionClassifier, build_loaders


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def run_epoch(model, loader, optimizer, criterion, device) -> float:
    model.train()
    running = 0.0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(images), labels)
        loss.backward()
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


def validate(model, loader, criterion, device) -> float:
    model.eval()
    total = 0.0
    seen = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            logits = model(images)
            total += criterion(logits, labels).item() * labels.numel()
            seen += labels.numel()
    model.train()
    return total / max(seen, 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vision-train")
    parser.add_argument("--data-root", default="data/images")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--out", default="artifacts/vision.pt")
    args = parser.parse_args(argv)

    seed_everything(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_loader, val_loader = build_loaders(args.data_root,
                                             batch_size=args.batch_size)
    model = VisionClassifier(classes=12).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    best = float("inf")
    for epoch in range(args.epochs):
        loss = run_epoch(model, train_loader, optimizer, criterion, device)
        val_loss = validate(model, val_loader, criterion, device)
        print("epoch %d train %.4f val %.4f" % (epoch, loss, val_loss))
        if val_loss < best:
            best = val_loss
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            torch.save(model.state_dict(), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
