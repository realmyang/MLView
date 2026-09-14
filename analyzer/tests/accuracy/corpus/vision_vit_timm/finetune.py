"""Fine-tune a pretrained ViT with mixup/cutmix.

Two objectives, on purpose: `SoftTargetCrossEntropy` for the mixed training
batches (whose targets are soft) and plain `CrossEntropyLoss` for validation
(whose targets are hard class indices). Both take logits; the model has no
activation on its head.
"""

from __future__ import annotations

import random

import numpy as np
import timm
import torch
import torch.nn as nn
from timm.loss import SoftTargetCrossEntropy
from timm.scheduler import CosineLRScheduler

from data import NUM_CLASSES, SEED, build_loaders, build_mixup, to_device

DATA_ROOT = "data/cifar100_folders"
MODEL_NAME = "vit_base_patch16_224"
EPOCHS = 30
BATCH_SIZE = 64
WORKERS = 8
LR = 5e-4
WEIGHT_DECAY = 0.05
CHECKPOINT = "vit_best.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_model(num_classes: int = NUM_CLASSES) -> nn.Module:
    """A pretrained backbone with a fresh head that returns logits."""
    return timm.create_model(MODEL_NAME, pretrained=True, num_classes=num_classes,
                             drop_path_rate=0.1)


def train_one_epoch(model, loader, criterion, optimizer, scheduler, mixup,
                    device, epoch: int) -> float:
    """Mixup is applied to the training batch and only to the training batch."""
    model.train()
    running = 0.0
    batches = 0
    steps_per_epoch = len(loader)
    for step, (images, targets) in enumerate(loader):
        images, targets = to_device(images, targets, device)
        images, soft_targets = mixup(images, targets)
        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, soft_targets)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        scheduler.step_update(epoch * steps_per_epoch + step)
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


@torch.no_grad()
def evaluate(model, loader, criterion, device) -> dict:
    """Hard targets, hard predictions: argmax before the accuracy count."""
    model.eval()
    total_loss = 0.0
    correct = 0
    seen = 0
    for images, targets in loader:
        images, targets = to_device(images, targets, device)
        logits = model(images)
        total_loss += criterion(logits, targets).item() * targets.size(0)
        predictions = logits.argmax(dim=1)
        correct += (predictions == targets).sum().item()
        seen += targets.size(0)
    model.train()
    return {"loss": total_loss / max(seen, 1), "acc": correct / max(seen, 1)}


def main() -> float:
    seed_everything()
    device = pick_device()
    train_loader, val_loader, test_loader = build_loaders(
        DATA_ROOT, batch_size=BATCH_SIZE, workers=WORKERS)

    model = build_model()
    model.to(device)
    mixup = build_mixup()

    train_criterion = SoftTargetCrossEntropy()
    eval_criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR,
                                  weight_decay=WEIGHT_DECAY)
    scheduler = CosineLRScheduler(optimizer, t_initial=EPOCHS * len(train_loader),
                                  warmup_t=len(train_loader), warmup_lr_init=1e-6)

    best_acc = 0.0
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, train_criterion,
                                     optimizer, scheduler, mixup, device, epoch)
        metrics = evaluate(model, val_loader, eval_criterion, device)
        print("epoch %d train_loss %.4f val_loss %.4f val_acc %.4f"
              % (epoch, train_loss, metrics["loss"], metrics["acc"]))
        if metrics["acc"] > best_acc:
            best_acc = metrics["acc"]
            torch.save({"model": model.state_dict(), "acc": best_acc}, CHECKPOINT)

    payload = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model.load_state_dict(payload["model"])
    final = evaluate(model, test_loader, eval_criterion, device)
    print("test acc %.4f" % final["acc"])
    return final["acc"]


if __name__ == "__main__":
    main()
