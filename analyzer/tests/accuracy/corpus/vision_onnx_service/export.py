"""Train the classifier, then export it to ONNX for the service.

The export runs with the module in eval mode and under `no_grad`, so the
BatchNorm statistics baked into the graph are the trained ones and dropout is
traced as an identity.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder
from torchvision.models import resnet18

from pipeline import CLASS_NAMES, IMAGE_SIZE, serving_transform, training_transform

SEED = 77
DATA_ROOT = "data/animals"
EPOCHS = 12
BATCH_SIZE = 32
WORKERS = 4
LR = 1e-3
ONNX_PATH = "classifier.onnx"
WEIGHTS_PATH = "classifier.pt"


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_model(classes: int = len(CLASS_NAMES)) -> nn.Module:
    model = resnet18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, classes)
    return model


def build_loaders():
    train_ds = ImageFolder("%s/train" % DATA_ROOT, transform=training_transform())
    val_ds = ImageFolder("%s/val" % DATA_ROOT, transform=serving_transform())
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=WORKERS, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=WORKERS, pin_memory=True)
    return train_loader, val_loader


def train_one_epoch(model, loader, criterion, optimizer, device) -> float:
    model.train()
    running = 0.0
    batches = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(images), labels)
        loss.backward()
        optimizer.step()
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


@torch.no_grad()
def evaluate(model, loader, device) -> float:
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        logits = model(images)
        correct += (logits.argmax(dim=1) == labels).sum().item()
        seen += labels.size(0)
    model.train()
    return correct / max(seen, 1)


@torch.no_grad()
def export_onnx(model: nn.Module, path: str = ONNX_PATH) -> str:
    """Trace on the CPU, in eval mode, with a dynamic batch axis."""
    model.eval()
    model.cpu()
    example = torch.randn(1, 3, IMAGE_SIZE, IMAGE_SIZE)
    torch.onnx.export(
        model,
        example,
        path,
        input_names=["images"],
        output_names=["logits"],
        dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    return path


def main() -> str:
    seed_everything()
    device = pick_device()
    train_loader, val_loader = build_loaders()

    model = build_model().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)

    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        accuracy = evaluate(model, val_loader, device)
        print("epoch %d loss %.4f val_acc %.4f" % (epoch, loss, accuracy))

    torch.save(model.state_dict(), WEIGHTS_PATH)
    return export_onnx(model)


if __name__ == "__main__":
    main()
