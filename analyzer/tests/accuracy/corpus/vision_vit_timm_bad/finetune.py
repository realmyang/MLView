"""Fine-tune a pretrained ViT (defective twin).

Defect 3: nothing seeds anything, so the RandAugment draw, the mixup draw and
the head initialisation all move between runs.
Defect 4: the gradients are computed but `optimizer.step()` is never called -
the refactor that introduced accumulation lost the step.
Defect 5: mixup is applied inside `evaluate`, so the validation batches are
blends of two images scored against blended labels.
Defect 6: `evaluate` never switches to eval mode, so the ViT's drop-path and
dropout stay active while the checkpoint is being selected.
Defect 7: the whole module is pickled by `torch.save`.
"""

from __future__ import annotations

import timm
import torch
import torch.nn as nn
from timm.loss import SoftTargetCrossEntropy
from timm.scheduler import CosineLRScheduler

from data import NUM_CLASSES, build_loaders, build_mixup, to_device

DATA_ROOT = "data/cifar100_folders"
MODEL_NAME = "vit_base_patch16_224"
EPOCHS = 30
BATCH_SIZE = 64
WORKERS = 8
LR = 5e-4
WEIGHT_DECAY = 0.05
CHECKPOINT = "vit_best.pt"


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_model(num_classes: int = NUM_CLASSES) -> nn.Module:
    return timm.create_model(MODEL_NAME, pretrained=True, num_classes=num_classes,
                             drop_path_rate=0.1)


def train_one_epoch(model, loader, criterion, optimizer, scheduler, mixup,
                    device, epoch: int) -> float:
    """Defect 4: backward() runs, step() never does."""
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
        scheduler.step_update(epoch * steps_per_epoch + step)
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


def evaluate(model, loader, criterion, mixup, device) -> dict:
    """Defects 5 and 6: mixup on the held-out data, and no eval mode."""
    total_loss = 0.0
    correct = 0
    seen = 0
    for images, targets in loader:
        images, targets = to_device(images, targets, device)
        images, soft_targets = mixup(images, targets)
        logits = model(images)
        total_loss += criterion(logits, soft_targets).item() * targets.size(0)
        predictions = logits.argmax(dim=1)
        correct += (predictions == targets).sum().item()
        seen += targets.size(0)
    return {"loss": total_loss / max(seen, 1), "acc": correct / max(seen, 1)}


def main() -> float:
    device = pick_device()
    train_loader, val_loader, test_loader = build_loaders(
        DATA_ROOT, batch_size=BATCH_SIZE, workers=WORKERS)

    model = build_model()
    model.to(device)
    mixup = build_mixup()

    train_criterion = SoftTargetCrossEntropy()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR,
                                  weight_decay=WEIGHT_DECAY)
    scheduler = CosineLRScheduler(optimizer, t_initial=EPOCHS * len(train_loader),
                                  warmup_t=len(train_loader), warmup_lr_init=1e-6)

    best_acc = 0.0
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, train_criterion,
                                     optimizer, scheduler, mixup, device, epoch)
        metrics = evaluate(model, val_loader, train_criterion, mixup, device)
        print("epoch %d train_loss %.4f val_loss %.4f val_acc %.4f"
              % (epoch, train_loss, metrics["loss"], metrics["acc"]))
        if metrics["acc"] > best_acc:
            best_acc = metrics["acc"]
            torch.save(model, CHECKPOINT)

    final = evaluate(model, test_loader, train_criterion, mixup, device)
    print("test acc %.4f" % final["acc"])
    return final["acc"]


if __name__ == "__main__":
    main()
