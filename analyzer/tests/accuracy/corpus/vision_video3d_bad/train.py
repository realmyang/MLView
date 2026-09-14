"""Train a video classifier (defective twin).

Defect 5: `forward` ends in a LogSoftmax while the objective is
`CrossEntropyLoss`, so the log-softmax runs twice.
Defect 6: the clips are never moved to the device the model lives on.
Defect 7: `evaluate` is called with the model still in train mode - with a 0.5
dropout and BatchNorm3d on every stage, the reported accuracy is noise and the
running statistics are overwritten by the validation clips.
Defect 8: `MultiStepLR` is stepped inside the batch loop, so the milestones at
epochs 20 and 35 are passed within the first thirty-five batches.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn

from clips import SEED, build_loaders

DATA_ROOT = "data/ucf101"
EPOCHS = 45
BATCH_SIZE = 8
WORKERS = 6
LR = 0.01
CHECKPOINT = "r2plus1d.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SpatioTemporalBlock(nn.Module):
    """A (2+1)D block: a spatial 1x3x3 then a temporal 3x1x1."""

    def __init__(self, cin: int, cout: int, stride: int = 1) -> None:
        super().__init__()
        mid = (cin * cout * 3 * 3 * 3) // (cin * 3 * 3 + 3 * cout)
        self.spatial = nn.Conv3d(cin, mid, (1, 3, 3),
                                 stride=(1, stride, stride), padding=(0, 1, 1),
                                 bias=False)
        self.spatial_norm = nn.BatchNorm3d(mid)
        self.temporal = nn.Conv3d(mid, cout, (3, 1, 1), stride=(stride, 1, 1),
                                  padding=(1, 0, 0), bias=False)
        self.temporal_norm = nn.BatchNorm3d(cout)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.spatial_norm(self.spatial(x)))
        return self.relu(self.temporal_norm(self.temporal(x)))


class VideoNet(nn.Module):
    """Defect 5: a LogSoftmax tail in front of CrossEntropyLoss."""

    def __init__(self, classes: int = 101, width: int = 64) -> None:
        super().__init__()
        self.stem = SpatioTemporalBlock(3, width)
        self.stages = nn.ModuleList([
            SpatioTemporalBlock(width, width * 2, stride=2),
            SpatioTemporalBlock(width * 2, width * 4, stride=2),
            SpatioTemporalBlock(width * 4, width * 8, stride=2),
        ])
        self.pool = nn.AdaptiveAvgPool3d(1)
        self.dropout = nn.Dropout(0.5)
        self.head = nn.Linear(width * 8, classes)
        self.log_softmax = nn.LogSoftmax(dim=1)

    def forward(self, clips: torch.Tensor) -> torch.Tensor:
        x = self.stem(clips)
        for stage in self.stages:
            x = stage(x)
        x = self.pool(x).flatten(1)
        return self.log_softmax(self.head(self.dropout(x)))


def train_one_epoch(model, loader, criterion, optimizer, scheduler, device) -> float:
    """Defects 6 and 8: no device move, and a per-epoch schedule per batch."""
    model.train()
    running = 0.0
    batches = 0
    for clips, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        logits = model(clips)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        scheduler.step()
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


def evaluate(model, loader, criterion, device) -> dict:
    """Defect 7: no eval(), no no_grad()."""
    total_loss = 0.0
    correct = 0
    seen = 0
    for clips, labels in loader:
        clips = clips.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        logits = model(clips)
        total_loss += criterion(logits, labels).item() * labels.size(0)
        correct += (logits.argmax(dim=1) == labels).sum().item()
        seen += labels.size(0)
    return {"loss": total_loss / max(seen, 1), "acc": correct / max(seen, 1)}


def main() -> float:
    seed_everything()
    device = pick_device()
    train_loader, val_loader, test_loader = build_loaders(
        DATA_ROOT, batch_size=BATCH_SIZE, workers=WORKERS)

    model = VideoNet(classes=101)
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=LR, momentum=0.9,
                                weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=[20, 35])

    best = 0.0
    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, train_loader, criterion, optimizer,
                               scheduler, device)
        metrics = evaluate(model, val_loader, criterion, device)
        print("epoch %d loss %.4f val_acc %.4f" % (epoch, loss, metrics["acc"]))
        if metrics["acc"] > best:
            best = metrics["acc"]
            torch.save({"model": model.state_dict()}, CHECKPOINT)

    payload = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model.load_state_dict(payload["model"])
    final = evaluate(model, test_loader, criterion, device)
    print("test acc %.4f" % final["acc"])
    return final["acc"]


if __name__ == "__main__":
    main()
