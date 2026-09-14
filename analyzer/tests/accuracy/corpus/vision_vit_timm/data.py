"""Fine-tuning data for a ViT: timm transforms, mixup, loaders.

`create_transform(is_training=True)` is the augmented pipeline; the evaluation
pipeline is built with `is_training=False`, which gives resize / centre-crop /
normalise and nothing random.
"""

from __future__ import annotations

import torch
from timm.data import Mixup, create_transform
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

IMAGE_SIZE = 224
MEAN = (0.5, 0.5, 0.5)
STD = (0.5, 0.5, 0.5)
SEED = 1337
NUM_CLASSES = 100


def train_transform():
    """RandAugment, random erasing, colour jitter - training only."""
    return create_transform(
        input_size=IMAGE_SIZE,
        is_training=True,
        auto_augment="rand-m9-mstd0.5-inc1",
        interpolation="bicubic",
        re_prob=0.25,
        mean=MEAN,
        std=STD,
    )


def eval_transform():
    """Deterministic resize + centre crop + normalise."""
    return create_transform(
        input_size=IMAGE_SIZE,
        is_training=False,
        crop_pct=0.9,
        interpolation="bicubic",
        mean=MEAN,
        std=STD,
    )


def build_mixup(num_classes: int = NUM_CLASSES) -> Mixup:
    """Mixup + CutMix with label smoothing, for the training batches only."""
    return Mixup(
        mixup_alpha=0.8,
        cutmix_alpha=1.0,
        prob=1.0,
        switch_prob=0.5,
        mode="batch",
        label_smoothing=0.1,
        num_classes=num_classes,
    )


def build_loaders(root: str, batch_size: int = 64, workers: int = 8):
    """One augmented training loader and two deterministic evaluation loaders."""
    train_ds = ImageFolder("%s/train" % root, transform=train_transform())
    val_ds = ImageFolder("%s/val" % root, transform=eval_transform())
    test_ds = ImageFolder("%s/test" % root, transform=eval_transform())

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, val_loader, test_loader


def to_device(images: torch.Tensor, targets: torch.Tensor, device: torch.device):
    return (images.to(device, non_blocking=True),
            targets.to(device, non_blocking=True))
