"""A modern single-GPU training script: `torch.compile`, `channels_last`,
bf16 autocast, activation checkpointing and an EMA of the weights.

Correct on purpose, including the two places this shape is usually wrong:

* bf16 autocast needs **no** `GradScaler` (bf16 has fp32's exponent range), so
  its absence is right, not an MLV208;
* the EMA update runs under `torch.no_grad()` and copies with `mul_`/`add_`,
  so nothing there accumulates an autograd graph.

Any finding in this file is a false positive.
"""
from __future__ import annotations

import argparse
import copy
import os
import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.checkpoint import checkpoint
from torch.utils.data import DataLoader, TensorDataset


class Block(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.norm1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.norm2 = nn.BatchNorm2d(channels)
        self.act = nn.SiLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.act(self.norm1(self.conv1(x)))
        return self.act(x + self.norm2(self.conv2(h)))


class ConvNet(nn.Module):
    def __init__(self, channels: int = 64, depth: int = 6,
                 classes: int = 10, use_checkpointing: bool = True) -> None:
        super().__init__()
        self.use_checkpointing = use_checkpointing
        self.stem = nn.Conv2d(3, channels, 3, padding=1, bias=False)
        self.blocks = nn.ModuleList([Block(channels) for _ in range(depth)])
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Linear(channels, classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.stem(x)
        for block in self.blocks:
            if self.use_checkpointing and self.training:
                h = checkpoint(block, h, use_reentrant=False)
            else:
                h = block(h)
        return self.head(self.pool(h).flatten(1))


class ModelEMA:
    """Exponential moving average of the trained weights."""

    def __init__(self, model: nn.Module, decay: float = 0.999) -> None:
        self.decay = decay
        self.module = copy.deepcopy(model).eval()
        for parameter in self.module.parameters():
            parameter.requires_grad_(False)

    @torch.no_grad()
    def update(self, model: nn.Module) -> None:
        for shadow, live in zip(self.module.state_dict().values(),
                                model.state_dict().values()):
            if shadow.dtype.is_floating_point:
                shadow.mul_(self.decay).add_(live.detach(),
                                             alpha=1.0 - self.decay)
            else:
                shadow.copy_(live)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_loaders(batch_size: int, workers: int):
    images = torch.randn(4096, 3, 32, 32)
    labels = torch.randint(0, 10, (4096,))
    train_set = TensorDataset(images[:3584], labels[:3584])
    val_set = TensorDataset(images[3584:], labels[3584:])
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True,
                              drop_last=True, persistent_workers=workers > 0)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    return train_loader, val_loader


def validate(model: nn.Module, loader, criterion, device, autocast_dtype):
    model.eval()
    total = 0.0
    seen = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device, memory_format=torch.channels_last,
                               non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            with torch.autocast(device_type=device.type,
                                dtype=autocast_dtype):
                logits = model(images)
                loss = criterion(logits, labels)
            total += loss.item() * labels.numel()
            seen += labels.numel()
    model.train()
    return total / max(seen, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="compile + bf16 + EMA")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="artifacts/convnet.pt")
    args = parser.parse_args()

    seed_everything(args.seed)
    torch.backends.cudnn.benchmark = True
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    autocast_dtype = torch.bfloat16 if device.type == "cuda" else torch.float32

    model = ConvNet().to(device, memory_format=torch.channels_last)
    ema = ModelEMA(model)
    compiled = torch.compile(model, mode="max-autotune")

    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=0.05, fused=device.type == "cuda")
    train_loader, val_loader = build_loaders(args.batch_size, args.workers)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr, epochs=args.epochs,
        steps_per_epoch=len(train_loader))

    best = float("inf")
    for epoch in range(args.epochs):
        compiled.train()
        for images, labels in train_loader:
            images = images.to(device, memory_format=torch.channels_last,
                               non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=autocast_dtype):
                logits = compiled(images)
                loss = criterion(logits, labels)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            ema.update(model)

        val_loss = validate(ema.module, val_loader, criterion, device,
                            autocast_dtype)
        print("epoch %d val_loss %.4f" % (epoch, val_loss))
        if val_loss < best:
            best = val_loss
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            torch.save({"model": model.state_dict(),
                        "ema": ema.module.state_dict(),
                        "epoch": epoch}, args.out)


if __name__ == "__main__":
    main()
