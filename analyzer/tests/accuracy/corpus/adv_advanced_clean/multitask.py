"""Multi-task learning with Kendall-style uncertainty weighting - correct.

One shared trunk, a classification head and a regression head, and a learnable
log-variance per task so the two losses are combined as
`exp(-s_i) * L_i + s_i` rather than with a hand-tuned constant. The
classification head returns raw logits to CrossEntropyLoss and the regression
head returns raw values to MSELoss, both correct pairings.

Nothing here is a defect. Any high-severity finding is a false positive. The
trap this file carries is the composed loss: three terms summed inside a helper
and back-propagated once, which is correct and must not be read as an
accumulated loss tensor (MLV205) or as a missing backward (MLV206).
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

SEED = 59
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 40
BATCH_SIZE = 128
NUM_CLASSES = 7


class MultiTaskNet(nn.Module):
    """A shared trunk plus one head per task, registered in a ModuleDict."""

    def __init__(self, in_features: int, num_classes: int) -> None:
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(in_features, 256),
            nn.LayerNorm(256),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(256, 128),
            nn.GELU(),
        )
        self.heads = nn.ModuleDict({
            "class": nn.Linear(128, num_classes),
            "value": nn.Linear(128, 1),
        })
        # One learnable log-variance per task, initialised at zero.
        self.log_vars = nn.Parameter(torch.zeros(2))

    def forward(self, features):
        shared = self.trunk(features)
        return self.heads["class"](shared), self.heads["value"](shared).squeeze(-1)


def uncertainty_weighted(class_loss, value_loss, log_vars):
    """Kendall & Gal's homoscedastic weighting, summed into one scalar."""
    class_term = torch.exp(-log_vars[0]) * class_loss + log_vars[0]
    value_term = torch.exp(-log_vars[1]) * value_loss + log_vars[1]
    return class_term + value_term


def train_one_epoch(model, loader, optimizer, class_criterion, value_criterion):
    model.train()
    running = 0.0
    for features, labels, targets in loader:
        features = features.to(DEVICE, non_blocking=True)
        labels = labels.to(DEVICE, non_blocking=True)
        targets = targets.to(DEVICE, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        logits, values = model(features)
        class_loss = class_criterion(logits, labels)
        value_loss = value_criterion(values, targets)
        total = uncertainty_weighted(class_loss, value_loss, model.log_vars)
        total.backward()
        optimizer.step()
        running += total.item()
    return running / max(1, len(loader))


@torch.no_grad()
def evaluate(model, loader, class_criterion, value_criterion):
    model.eval()
    class_total = 0.0
    value_total = 0.0
    correct = 0
    seen = 0
    for features, labels, targets in loader:
        features = features.to(DEVICE, non_blocking=True)
        labels = labels.to(DEVICE, non_blocking=True)
        targets = targets.to(DEVICE, non_blocking=True)
        logits, values = model(features)
        class_total += class_criterion(logits, labels).item()
        value_total += value_criterion(values, targets).item()
        correct += int((logits.argmax(dim=-1) == labels).sum().item())
        seen += int(labels.shape[0])
    return (class_total / max(1, len(loader)),
            value_total / max(1, len(loader)),
            correct / max(1, seen))


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    features = torch.randn(8192, 64)
    labels = torch.randint(0, NUM_CLASSES, (8192,))
    targets = torch.randn(8192)
    generator = torch.Generator().manual_seed(SEED)
    train_set, val_set = torch.utils.data.random_split(
        TensorDataset(features, labels, targets), [0.85, 0.15], generator=generator)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=2, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=2)

    model = MultiTaskNet(64, NUM_CLASSES).to(DEVICE)
    class_criterion = nn.CrossEntropyLoss()
    value_criterion = nn.MSELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

    best = float("inf")
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, optimizer,
                                     class_criterion, value_criterion)
        class_loss, value_loss, accuracy = evaluate(
            model, val_loader, class_criterion, value_criterion)
        scheduler.step()
        if class_loss + value_loss < best:
            best = class_loss + value_loss
            torch.save(model.state_dict(), "multitask.pt")
        print("epoch %d train %.4f class %.4f value %.4f acc %.4f"
              % (epoch, train_loss, class_loss, value_loss, accuracy))


if __name__ == "__main__":
    main()
