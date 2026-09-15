"""Multi-task training with the 2024 PyTorch performance stack:
`channels_last`, `torch.compile`, bfloat16 autocast and gradient accumulation.

Three shapes look wrong and are not.

* bfloat16 autocast runs **without** a `GradScaler`. bf16 has fp32's exponent
  range, so there is nothing to scale; a scaler here would be the mistake.
* `optimizer.zero_grad()` and `optimizer.step()` sit inside
  `if (step + 1) % accum == 0`, which is what gradient accumulation is.
* the model is rebound to `torch.compile(model)` **before** the optimizer is
  built, so the optimizer owns the parameters the compiled module runs.
"""

from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from data import MultiTaskDataset, eval_augment, train_augment, multitask_collate
from model import MultiTaskLoss, MultiTaskNet


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(args):
    train_set = MultiTaskDataset(args.data, split="train", augment=train_augment())
    val_set = MultiTaskDataset(args.data, split="val", augment=eval_augment())
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.workers, pin_memory=True,
                              drop_last=True, collate_fn=multitask_collate)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False,
                            num_workers=args.workers, pin_memory=True,
                            collate_fn=multitask_collate)
    return train_loader, val_loader


def move(batch, device):
    images = batch["images"].to(device, memory_format=torch.channels_last,
                                non_blocking=True)
    targets = {key: value.to(device, non_blocking=True)
               for key, value in batch["targets"].items()}
    return images, targets


def train_one_epoch(model, loader, criterion, optimizer, scheduler, device, args):
    model.train()
    running = 0.0
    seen = 0
    optimizer.zero_grad(set_to_none=True)
    for step, batch in enumerate(loader):
        images, targets = move(batch, device)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16,
                            enabled=args.amp):
            outputs = model(images)
            losses = criterion(outputs, targets)
            loss = losses["total"] / args.accum
        loss.backward()
        if (step + 1) % args.accum == 0:
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=10.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)
        running += losses["total"].item() * images.size(0)
        seen += images.size(0)
    return running / max(1, seen)


@torch.no_grad()
def evaluate(model, loader, criterion, device, args):
    model.eval()
    total = 0.0
    intersection = 0.0
    union = 0.0
    correct = 0
    counted = 0
    for batch in loader:
        images, targets = move(batch, device)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16,
                            enabled=args.amp):
            outputs = model(images)
            losses = criterion(outputs, targets)
        total += losses["total"].item() * images.size(0)

        predicted_mask = (torch.sigmoid(outputs["masks"]) > 0.5).float()
        intersection += (predicted_mask * targets["masks"]).sum().item()
        union += (predicted_mask + targets["masks"]).clamp(max=1.0).sum().item()

        predicted_class = outputs["classes"].argmax(dim=1)
        valid = targets["classes"] >= 0
        correct += (predicted_class[valid] == targets["classes"][valid]).sum().item()
        counted += int(valid.sum().item())
    model.train()
    return (total / max(1, len(loader.dataset)),
            intersection / max(1.0, union),
            correct / max(1, counted))


def parse_args():
    parser = argparse.ArgumentParser(description="Multi-task detection + segmentation")
    parser.add_argument("--data", default="data/multitask")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--compile", dest="compile_model", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--out", default="runs/multitask")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args)
    model = MultiTaskNet().to(device, memory_format=torch.channels_last)
    if args.compile_model:
        model = torch.compile(model, mode="max-autotune")
    criterion = MultiTaskLoss().to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=0.05)
    steps_per_epoch = max(1, len(train_loader) // args.accum)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr, epochs=args.epochs,
        steps_per_epoch=steps_per_epoch)

    best = 0.0
    for epoch in range(args.epochs):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer,
                                     scheduler, device, args)
        val_loss, iou, accuracy = evaluate(model, val_loader, criterion, device,
                                           args)
        print("epoch %d train %.4f val %.4f iou %.4f acc %.4f"
              % (epoch, train_loss, val_loss, iou, accuracy))
        if iou > best:
            best = iou
            torch.save({"model": model.state_dict(), "epoch": epoch, "iou": iou},
                       os.path.join(args.out, "best.pt"))
    print("best iou %.4f" % best)


if __name__ == "__main__":
    main()
