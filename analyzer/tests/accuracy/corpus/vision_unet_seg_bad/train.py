"""The segmentation training entrypoint (defective twin).

Defect 6: `optimizer.step()` runs before `loss.backward()`, so every update
uses the previous batch's gradients.
Defect 7: the epoch loss is accumulated as a live tensor.
Defect 8: `validate()` neither switches to eval mode nor disables autograd, so
the Dropout2d layer fires and the BatchNorm statistics keep moving while the
validation IoU is measured.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn

from data import SEED, build_loaders
from model import build_model, iou_score

DATA_ROOT = "data/segmentation"
EPOCHS = 40
BATCH_SIZE = 4
WORKERS = 4
LR = 3e-4
CLIP_NORM = 1.0
CHECKPOINT = "unet_best.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def train_one_epoch(model, loader, criterion, optimizer, device):
    """Defects 6 and 7."""
    model.train()
    running = 0.0
    batches = 0
    for images, masks in loader:
        images = images.to(device, non_blocking=True)
        masks = masks.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, masks)
        optimizer.step()
        loss.backward()
        running += loss
        batches += 1
    return running / max(batches, 1)


def validate(model, loader, criterion, device) -> dict:
    """Defect 8: train mode, gradients on."""
    total_loss = 0.0
    total_iou = 0.0
    batches = 0
    for images, masks in loader:
        images = images.to(device, non_blocking=True)
        masks = masks.to(device, non_blocking=True)
        logits = model(images)
        total_loss += criterion(logits, masks).item()
        total_iou += iou_score(logits, masks)
        batches += 1
    return {"loss": total_loss / max(batches, 1),
            "iou": total_iou / max(batches, 1)}


def main() -> float:
    seed_everything()
    device = pick_device()
    train_loader, val_loader, test_loader = build_loaders(
        DATA_ROOT, batch_size=BATCH_SIZE, workers=WORKERS)

    model = build_model(classes=1)
    model.to(device)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    best_iou = 0.0
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer,
                                     device)
        scheduler.step()
        metrics = validate(model, val_loader, criterion, device)
        print("epoch %d train_loss %.4f val_loss %.4f val_iou %.4f"
              % (epoch, float(train_loss), metrics["loss"], metrics["iou"]))
        if metrics["iou"] > best_iou:
            best_iou = metrics["iou"]
            torch.save({"model": model.state_dict(), "iou": best_iou}, CHECKPOINT)

    payload = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model.load_state_dict(payload["model"])
    final = validate(model, test_loader, criterion, device)
    print("test iou %.4f" % final["iou"])
    return final["iou"]


if __name__ == "__main__":
    main()
