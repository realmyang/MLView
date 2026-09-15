"""SimCLR pre-training and the linear probe that reports on it.

NT-Xent is written out rather than imported: the two views are concatenated,
the similarity matrix is masked on its diagonal, and the positives sit at an
offset of `batch`. `CrossEntropyLoss` consumes the raw similarity logits.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet18

from data import SEED, build_pretrain_loader, build_probe_loaders

EPOCHS = 200
PROBE_EPOCHS = 20
BATCH_SIZE = 512
WORKERS = 8
LR = 1e-3
TEMPERATURE = 0.5
FEATURE_DIM = 128
CHECKPOINT = "simclr_encoder.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SimCLR(nn.Module):
    """A ResNet-18 encoder with a two-layer projection head."""

    def __init__(self, feature_dim: int = FEATURE_DIM) -> None:
        super().__init__()
        backbone = resnet18(weights=None)
        backbone.fc = nn.Identity()
        self.encoder = backbone
        self.projector = nn.Sequential(
            nn.Linear(512, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Linear(512, feature_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.encoder(x)
        return F.normalize(self.projector(features), dim=1)

    def represent(self, x: torch.Tensor) -> torch.Tensor:
        return self.encoder(x)


def nt_xent(projections: torch.Tensor, batch: int, temperature: float,
            criterion: nn.Module) -> torch.Tensor:
    """Similarity logits for 2N views, positives at an offset of N."""
    similarity = projections @ projections.t() / temperature
    mask = torch.eye(2 * batch, dtype=torch.bool, device=projections.device)
    similarity = similarity.masked_fill(mask, float("-inf"))
    targets = torch.arange(2 * batch, device=projections.device)
    targets = (targets + batch) % (2 * batch)
    return criterion(similarity, targets)


def pretrain(epochs: int = EPOCHS) -> nn.Module:
    seed_everything()
    device = pick_device()
    loader = build_pretrain_loader(batch_size=BATCH_SIZE, workers=WORKERS)

    model = SimCLR().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-6)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    for epoch in range(epochs):
        model.train()
        running = 0.0
        batches = 0
        for (view_one, view_two), _labels in loader:
            view_one = view_one.to(device, non_blocking=True)
            view_two = view_two.to(device, non_blocking=True)
            batch = view_one.size(0)

            optimizer.zero_grad(set_to_none=True)
            projections = model(torch.cat([view_one, view_two], dim=0))
            loss = nt_xent(projections, batch, TEMPERATURE, criterion)
            loss.backward()
            optimizer.step()

            running += loss.item()
            batches += 1

        scheduler.step()
        print("epoch %d nt_xent %.4f" % (epoch, running / max(batches, 1)))

    torch.save({"model": model.state_dict()}, CHECKPOINT)
    return model


def linear_probe(model: nn.Module, device: torch.device) -> float:
    """Freeze the encoder, fit a linear classifier, report test accuracy."""
    train_loader, test_loader = build_probe_loaders(workers=WORKERS)
    classifier = nn.Linear(512, 10).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(classifier.parameters(), lr=1e-3)

    model.eval()
    for _epoch in range(PROBE_EPOCHS):
        for images, labels in train_loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            with torch.no_grad():
                features = model.represent(images)
            optimizer.zero_grad(set_to_none=True)
            logits = classifier(features)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

    return evaluate(model, classifier, test_loader, device)


@torch.no_grad()
def evaluate(model: nn.Module, classifier: nn.Module, loader, device) -> float:
    model.eval()
    classifier.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        logits = classifier(model.represent(images))
        correct += (logits.argmax(dim=1) == labels).sum().item()
        seen += labels.size(0)
    return correct / max(seen, 1)


def main() -> float:
    device = pick_device()
    model = pretrain()
    accuracy = linear_probe(model, device)
    print("linear probe top1 %.4f" % accuracy)
    return accuracy


if __name__ == "__main__":
    main()
