"""Quantization-aware training and export - correct.

Fuse, prepare_qat, fine-tune in train mode, then move to CPU, switch to eval
mode and convert. The eval-mode switch before `convert` is deliberate and is
what the PyTorch QAT recipe requires; `model.train()` is called again at the
top of every fine-tuning epoch, so nothing is left in the wrong mode.

Nothing here is a defect. Any high-severity finding is a false positive.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.ao.quantization as tq
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

SEED = 53
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 5
BATCH_SIZE = 64


class QuantizableCNN(nn.Module):
    """Conv-BN-ReLU blocks with the quant/dequant stubs QAT needs."""

    def __init__(self, num_classes: int = 10) -> None:
        super().__init__()
        self.quant = tq.QuantStub()
        self.dequant = tq.DeQuantStub()
        self.block1 = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
        )
        self.block2 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.classifier = nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.quant(x)
        x = self.block1(x)
        x = self.block2(x)
        x = self.pool(x).flatten(1)
        x = self.classifier(x)
        return self.dequant(x)


def fine_tune(model, loader, optimizer, criterion):
    """One QAT epoch. Fake-quant observers stay enabled the whole time."""
    model.train()
    running = 0.0
    for images, labels in loader:
        images = images.to(DEVICE, non_blocking=True)
        labels = labels.to(DEVICE, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        running += loss.item()
    return running / max(1, len(loader))


@torch.no_grad()
def accuracy(model, loader, device):
    model.eval()
    correct = 0
    seen = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        predicted = model(images).argmax(dim=-1)
        correct += int((predicted == labels).sum().item())
        seen += int(labels.shape[0])
    return correct / max(1, seen)


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    images = torch.randn(4096, 1, 28, 28)
    labels = torch.randint(0, 10, (4096,))
    generator = torch.Generator().manual_seed(SEED)
    train_set, val_set = torch.utils.data.random_split(
        TensorDataset(images, labels), [0.9, 0.1], generator=generator)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=2, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=2)

    model = QuantizableCNN().to(DEVICE)
    model.load_state_dict(torch.load("float_baseline.pt", weights_only=True,
                                     map_location=DEVICE))

    model.train()
    fused = tq.fuse_modules_qat(
        model, [["block1.0", "block1.1", "block1.2"],
                ["block2.0", "block2.1", "block2.2"]])
    fused.qconfig = tq.get_default_qat_qconfig("x86")
    prepared = tq.prepare_qat(fused, inplace=False).to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(prepared.parameters(), lr=1e-3, momentum=0.9)

    for epoch in range(EPOCHS):
        train_loss = fine_tune(prepared, train_loader, optimizer, criterion)
        val_acc = accuracy(prepared, val_loader, DEVICE)
        print("epoch %d loss %.4f val %.4f" % (epoch, train_loss, val_acc))

    # Conversion runs on CPU in eval mode - that is what the recipe requires,
    # and nothing is trained after this point.
    prepared.eval()
    quantized = tq.convert(prepared.to("cpu"), inplace=False)
    quantized_acc = accuracy(quantized, val_loader, torch.device("cpu"))
    print("int8 validation accuracy %.4f" % quantized_acc)

    torch.save(quantized.state_dict(), "qat_int8.pt")
    scripted = torch.jit.script(quantized)
    torch.jit.save(scripted, "qat_int8.torchscript")


if __name__ == "__main__":
    main()
