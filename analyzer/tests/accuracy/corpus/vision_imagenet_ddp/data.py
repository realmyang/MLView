"""Datasets, transforms and distributed loaders.

The two transform pipelines are kept apart on purpose: every random operator
lives in `train_transform()` and the evaluation pipeline is deterministic
resize -> centre crop -> tensor -> normalise.
"""

from __future__ import annotations

import torch
from torch.utils.data import DataLoader, DistributedSampler
from torchvision import transforms
from torchvision.datasets import ImageFolder

from config import CFG, DATA_ROOT, SEED


def train_transform() -> transforms.Compose:
    """Scale/aspect jitter, flip and colour jitter - training only."""
    return transforms.Compose([
        transforms.RandomResizedCrop(CFG.image_size, scale=(0.08, 1.0)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.4),
        transforms.ToTensor(),
        transforms.Normalize(CFG.channels, CFG.channel_std),
        transforms.RandomErasing(p=0.25),
    ])


def eval_transform() -> transforms.Compose:
    """Deterministic: the same image gives the same tensor on every epoch."""
    resize = int(CFG.image_size / CFG.crop_pct)
    return transforms.Compose([
        transforms.Resize(resize),
        transforms.CenterCrop(CFG.image_size),
        transforms.ToTensor(),
        transforms.Normalize(CFG.channels, CFG.channel_std),
    ])


class Split:
    """The three directory names ImageFolder expects under DATA_ROOT."""

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


def build_datasets(root: str = DATA_ROOT):
    """Three ImageFolder datasets, each with the transform it should have."""
    train_ds = ImageFolder("%s/%s" % (root, Split.TRAIN), transform=train_transform())
    val_ds = ImageFolder("%s/%s" % (root, Split.VAL), transform=eval_transform())
    test_ds = ImageFolder("%s/%s" % (root, Split.TEST), transform=eval_transform())
    return train_ds, val_ds, test_ds


def build_loaders(distributed: bool, rank: int = 0, world_size: int = 1):
    """Loaders for all three splits.

    The training loader is fed by a `DistributedSampler`, which shuffles; the
    evaluation loaders keep dataset order so predictions stay aligned with the
    file list a confusion matrix is read against.
    """
    train_ds, val_ds, test_ds = build_datasets()

    train_sampler = None
    if distributed:
        train_sampler = DistributedSampler(train_ds, num_replicas=world_size,
                                           rank=rank, shuffle=True, seed=SEED)

    train_loader = DataLoader(
        train_ds,
        batch_size=CFG.batch_size,
        shuffle=(train_sampler is None),
        sampler=train_sampler,
        num_workers=CFG.workers,
        pin_memory=True,
        drop_last=True,
        persistent_workers=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=CFG.eval_batch_size,
        shuffle=False,
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
    return train_loader, val_loader, test_loader, train_sampler


def move_batch(batch, device: torch.device):
    """Put one (images, targets) pair on the training device."""
    images, targets = batch
    images = images.to(device, non_blocking=True)
    targets = targets.to(device, non_blocking=True)
    return images, targets
