"""Quantization-aware training and export - the defective version.

The twin of `adv_advanced_clean/qat_export.py`. Nine defects. The three that
matter most to anyone who has shipped a quantized model are specific to the
QAT lifecycle and no rule models them: the observers calibrated on the test
loader, the `convert()` run on a module that is still in train mode - so the
quantization parameters are frozen from the wrong statistics - and the TorchScript
trace taken before `eval()`, which bakes the dropout mask into the exported
graph.
"""

from __future__ import annotations

import torch
import torch.ao.quantization as tq
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

EPOCHS = 5
# DEFECT: cuda named outright with no availability check.
DEVICE = torch.device("cuda")


class QuantisableNet(nn.Module):
    def __init__(self, num_classes: int = 10) -> None:
        super().__init__()
        self.quant = tq.QuantStub()
        self.dequant = tq.DeQuantStub()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.dropout = nn.Dropout(0.4)
        self.head = nn.Linear(32, num_classes)

    def forward(self, x):
        x = self.quant(x)
        h = self.features(x).flatten(1)
        return self.dequant(self.head(self.dropout(h)))


def build_loaders(root: str):
    to_tensor = transforms.Compose([transforms.ToTensor()])
    train_set = datasets.CIFAR10(root, train=True, transform=to_tensor)
    test_set = datasets.CIFAR10(root, train=False, transform=to_tensor)
    # DEFECT: the training loader does not shuffle.
    # DEFECT: num_workers=4 with no `if __name__ == "__main__"` guard anywhere.
    train_loader = DataLoader(train_set, batch_size=64, shuffle=False,
                              num_workers=4)
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False)
    return train_loader, test_loader


def calibrate(model, loader, batches: int = 20) -> None:
    """DEFECT: the observers are calibrated on the TEST loader, so the
    quantization ranges are chosen from the held-out distribution, and DEFECT:
    the pass runs without model.eval() and without torch.no_grad()."""
    for index, (images, _) in enumerate(loader):
        model(images.to(DEVICE))
        if index >= batches:
            break


def train_epoch(model, loader, criterion, optimizer) -> float:
    model.train()
    running = 0.0
    for images, labels in loader:
        images = images.to(DEVICE)
        labels = labels.to(DEVICE)
        logits = model(images)
        loss = criterion(logits, labels)
        # DEFECT: the gradients are never zeroed.
        loss.backward()
        optimizer.step()
        running += loss.item()
    return running


def export(model, example) -> None:
    """DEFECT: convert() runs on a module still in train mode, so the fake
    quantization parameters are frozen from training-time statistics, and
    DEFECT: the trace is taken before eval(), baking the 0.4 dropout mask into
    the exported graph."""
    converted = tq.convert(model, inplace=False)
    traced = torch.jit.trace(converted, example)
    torch.jit.save(traced, "model_int8.pt")
    # DEFECT: the float checkpoint is pickled whole rather than as a state_dict.
    torch.save(model, "model_fp32.pt")


def main() -> None:
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    train_loader, test_loader = build_loaders("data/cifar10")
    model = QuantisableNet().to(DEVICE)
    model.qconfig = tq.get_default_qat_qconfig("fbgemm")
    tq.prepare_qat(model, inplace=True)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_loader, criterion, optimizer)
        print("epoch %d loss %.4f" % (epoch, loss))

    calibrate(model, test_loader)
    example = torch.rand(1, 3, 32, 32, device=DEVICE)
    export(model, example)

    # DEFECT: torch.load with neither map_location= nor weights_only=.
    restored = torch.load("model_fp32.pt")
    print(restored)


main()
