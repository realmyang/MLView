"""PGD adversarial training and robust evaluation - correct, and a trap.

Adversarial training is the advanced pattern that breaks the two assumptions
the MLV2xx and MLV3xx families rest on:

* the attack calls `.backward()` on a loss whose gradient is taken with respect
  to the **input** - a leaf tensor - and never steps an optimizer, which is the
  exact shape MLV202 fires on;
* robust evaluation **must** run with gradients enabled, because the attack it
  measures is itself a gradient computation, so the missing `torch.no_grad()`
  in `evaluate_robust` is correct and the `model.eval()` above it is what makes
  it honest.

Everything in this file is correct. A `high`- or `medium`-severity finding here
is a false positive on the standard implementation of a published method.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

SEED = 5
EPOCHS = 20
EPSILON = 8.0 / 255.0
ALPHA = 2.0 / 255.0
PGD_STEPS = 7
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class SmallResNet(nn.Module):
    def __init__(self, num_classes: int = 10) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.dropout = nn.Dropout(0.3)
        self.head = nn.Linear(64, num_classes)

    def forward(self, x):
        h = self.features(x).flatten(1)
        return self.head(self.dropout(h))


def pgd_attack(model, images, labels, epsilon, alpha, steps):
    """Gradients with respect to the INPUT: no optimizer is involved."""
    delta = torch.empty_like(images).uniform_(-epsilon, epsilon)
    delta = torch.clamp(images + delta, 0.0, 1.0) - images
    delta.requires_grad_(True)
    for _ in range(steps):
        logits = model(images + delta)
        attack_loss = F.cross_entropy(logits, labels)
        grad = torch.autograd.grad(attack_loss, delta, only_inputs=True)[0]
        with torch.no_grad():
            delta.add_(alpha * grad.sign())
            delta.clamp_(-epsilon, epsilon)
            delta.copy_(torch.clamp(images + delta, 0.0, 1.0) - images)
    return (images + delta).detach()


def train_epoch(model, loader, criterion, optimizer) -> float:
    model.train()
    running = 0.0
    seen = 0
    for images, labels in loader:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        adversarial = pgd_attack(model, images, labels, EPSILON, ALPHA, PGD_STEPS)
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(adversarial), labels)
        loss.backward()
        optimizer.step()
        running += loss.item()
        seen += 1
    return running / max(seen, 1)


@torch.no_grad()
def evaluate_clean(model, loader) -> float:
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        predicted = model(images).argmax(dim=-1)
        correct += int((predicted == labels).sum())
        seen += labels.numel()
    return correct / max(seen, 1)


def evaluate_robust(model, loader) -> float:
    """No `torch.no_grad()` on purpose: the attack inside needs gradients.

    `model.eval()` is what makes the measurement honest - dropout off,
    BatchNorm in inference mode - and the gradient that is built here flows to
    the input, never to a parameter, because no optimizer is stepped.
    """
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        adversarial = pgd_attack(model, images, labels, EPSILON, ALPHA, PGD_STEPS)
        with torch.no_grad():
            predicted = model(adversarial).argmax(dim=-1)
        correct += int((predicted == labels).sum())
        seen += labels.numel()
    return correct / max(seen, 1)


def main() -> None:
    seed_everything(SEED)
    generator = torch.Generator().manual_seed(SEED)
    train_set = TensorDataset(torch.rand(512, 3, 32, 32), torch.randint(0, 10, (512,)))
    test_set = TensorDataset(torch.rand(128, 3, 32, 32), torch.randint(0, 10, (128,)))
    train_loader = DataLoader(train_set, batch_size=64, shuffle=True,
                              generator=generator)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False)

    model = SmallResNet().to(DEVICE)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1, momentum=0.9)

    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_loader, criterion, optimizer)
        clean = evaluate_clean(model, test_loader)
        robust = evaluate_robust(model, test_loader)
        print("epoch %d loss %.4f clean %.4f robust %.4f"
              % (epoch, loss, clean, robust))
    torch.save(model.state_dict(), "pgd_model.pt")


if __name__ == "__main__":
    main()
