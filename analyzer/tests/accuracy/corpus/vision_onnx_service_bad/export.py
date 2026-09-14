"""Train and export the classifier (defective twin).

Defect 3: the model carries a Softmax head while the loss is
`CrossEntropyLoss`.
Defect 4: the export traces the module in *train* mode, so the ONNX graph
freezes whatever BatchNorm statistics the last training batch left behind and
bakes dropout in as a real dropout node.
Defect 5: the checkpoint is reloaded with a bare `torch.load`.
Defect 6: the device is pinned to CUDA with no availability check.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder
from torchvision.models import resnet18

from pipeline import CLASS_NAMES, IMAGE_SIZE, eval_transform, training_transform

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
    """Defect 6: no torch.cuda.is_available() anywhere in the project."""
    return torch.device("cuda:0")


class Classifier(nn.Module):
    """Defect 3: a softmax head in front of CrossEntropyLoss."""

    def __init__(self, classes: int = len(CLASS_NAMES)) -> None:
        super().__init__()
        backbone = resnet18(weights=None)
        backbone.fc = nn.Linear(backbone.fc.in_features, classes)
        self.backbone = backbone
        self.softmax = nn.Softmax(dim=1)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.softmax(self.backbone(images))


def build_loaders():
    train_ds = ImageFolder("%s/train" % DATA_ROOT, transform=training_transform())
    val_ds = ImageFolder("%s/val" % DATA_ROOT, transform=eval_transform())
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


def export_onnx(model: nn.Module, path: str = ONNX_PATH) -> str:
    """Defect 4: traced in train mode."""
    model.train()
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

    model = Classifier().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)

    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        accuracy = evaluate(model, val_loader, device)
        print("epoch %d loss %.4f val_acc %.4f" % (epoch, loss, accuracy))

    torch.save(model.state_dict(), WEIGHTS_PATH)
    model.load_state_dict(torch.load(WEIGHTS_PATH))
    return export_onnx(model)


if __name__ == "__main__":
    main()
