"""SimCLR pre-training and the linear probe (defective twin).

Defect 4: the projection head ends in a `nn.Softmax`, and the NT-Xent
similarity logits are then fed to `CrossEntropyLoss` - a second log-softmax on
top of an already-normalised head.
Defect 5: the probe's feature extraction is no longer wrapped in `no_grad`,
and `model.eval()` is never called, so the encoder's BatchNorm statistics are
updated by the probe and by the final test pass.
Defect 6: the contrastive loss is accumulated as a live tensor.
Defect 7: the encoder is checkpointed by pickling the module.
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
    """Defect 4: a softmax at the end of the projection head."""

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
            nn.Softmax(dim=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.encoder(x)
        return self.projector(features)

    def represent(self, x: torch.Tensor) -> torch.Tensor:
        return self.encoder(x)


def pretrain(epochs: int = EPOCHS) -> nn.Module:
    seed_everything()
    device = pick_device()
    loader = build_pretrain_loader(batch_size=BATCH_SIZE, workers=WORKERS)

    model = SimCLR().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=1e-6)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    running = 0.0
    for epoch in range(epochs):
        model.train()
        batches = 0
        for (view_one, view_two), _labels in loader:
            view_one = view_one.to(device, non_blocking=True)
            view_two = view_two.to(device, non_blocking=True)
            batch = view_one.size(0)

            optimizer.zero_grad(set_to_none=True)
            projections = model(torch.cat([view_one, view_two], dim=0))
            similarity = projections @ projections.t() / TEMPERATURE
            mask = torch.eye(2 * batch, dtype=torch.bool, device=device)
            similarity = similarity.masked_fill(mask, float("-inf"))
            targets = (torch.arange(2 * batch, device=device) + batch) % (2 * batch)
            loss = criterion(similarity, targets)
            loss.backward()
            optimizer.step()

            running += loss
            batches += 1

        scheduler.step()
        print("epoch %d nt_xent %.4f" % (epoch, float(running) / max(batches, 1)))

    torch.save(model, CHECKPOINT)
    return model


def linear_probe(model: nn.Module, device: torch.device) -> float:
    """Defect 5: the encoder is neither frozen nor put in eval mode."""
    train_loader, test_loader = build_probe_loaders(workers=WORKERS)
    classifier = nn.Linear(512, 10).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(classifier.parameters(), lr=1e-3)

    for _epoch in range(PROBE_EPOCHS):
        for images, labels in train_loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            features = model.represent(images)
            optimizer.zero_grad(set_to_none=True)
            logits = classifier(features)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

    return evaluate(model, classifier, test_loader, device)


def evaluate(model: nn.Module, classifier: nn.Module, loader, device) -> float:
    """Defect 5, the other half: no eval(), no no_grad()."""
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
