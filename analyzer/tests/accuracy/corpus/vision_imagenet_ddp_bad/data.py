"""Datasets, transforms and loaders (defective twin).

Defect 2: the evaluation pipeline was copied from the training pipeline and
still carries RandomResizedCrop, the horizontal flip and the colour jitter, so
every epoch scores a different random crop of the validation set.
Defect 3: the training loader neither shuffles nor carries a sampler.
Defect 4: the validation loader shuffles.
"""

from __future__ import annotations

import torch
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import ImageFolder

from config import CFG, DATA_ROOT


def train_transform() -> transforms.Compose:
    """Scale/aspect jitter, flip and colour jitter - training only."""
    return transforms.Compose([
        transforms.RandomResizedCrop(CFG.image_size, scale=(0.08, 1.0)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.4),
        transforms.ToTensor(),
        transforms.Normalize(CFG.channels, CFG.channel_std),
    ])


def eval_transform() -> transforms.Compose:
    """Defect 2: this is the training pipeline with a different name."""
    return transforms.Compose([
        transforms.RandomResizedCrop(CFG.image_size, scale=(0.08, 1.0)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.4),
        transforms.ToTensor(),
        transforms.Normalize(CFG.channels, CFG.channel_std),
    ])


class Split:
    """The three directory names ImageFolder expects under DATA_ROOT."""

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


def build_datasets(root: str = DATA_ROOT):
    train_ds = ImageFolder("%s/%s" % (root, Split.TRAIN), transform=train_transform())
    val_ds = ImageFolder("%s/%s" % (root, Split.VAL), transform=eval_transform())
    test_ds = ImageFolder("%s/%s" % (root, Split.TEST), transform=eval_transform())
    return train_ds, val_ds, test_ds


def build_loaders(distributed: bool = False, rank: int = 0, world_size: int = 1):
    """Three loaders, two of them with the wrong shuffle setting."""
    train_ds, val_ds, test_ds = build_datasets()

    train_loader = DataLoader(
        train_ds,
        batch_size=CFG.batch_size,
        shuffle=False,
        num_workers=CFG.workers,
        pin_memory=True,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=CFG.eval_batch_size,
        shuffle=True,
        num_workers=CFG.workers,
        pin_memory=True,
    )
    test_loader = DataLoader(
        test_ds,
        batch_size=CFG.eval_batch_size,
        shuffle=False,
        num_workers=CFG.workers,
        pin_memory=True,
    )
    return train_loader, val_loader, test_loader, None


def move_batch(batch, device: torch.device):
    """Put one (images, targets) pair on the training device."""
    images, targets = batch
    images = images.to(device, non_blocking=True)
    targets = targets.to(device, non_blocking=True)
    return images, targets
