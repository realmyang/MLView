"""SimCLR views: one image in, two independently augmented crops out.

The contrastive pipeline is deliberately aggressive; the linear-probe
evaluation pipeline that scores the frozen encoder is deliberately not.
"""

from __future__ import annotations

from typing import Tuple

import torch
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import CIFAR10

SEED = 3407
DATA_ROOT = "data/cifar10"
IMAGE_SIZE = 32
MEAN = (0.4914, 0.4822, 0.4465)
STD = (0.2470, 0.2435, 0.2616)


class TwoCropsTransform:
    """Apply the same random pipeline twice and return both draws."""

    def __init__(self, pipeline: transforms.Compose) -> None:
        self.pipeline = pipeline

    def __call__(self, image) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.pipeline(image), self.pipeline(image)


def contrastive_pipeline() -> transforms.Compose:
    """Crop, flip, colour jitter, grayscale - the SimCLR recipe."""
    return transforms.Compose([
        transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.2, 1.0)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomApply([transforms.ColorJitter(0.4, 0.4, 0.4, 0.1)], p=0.8),
        transforms.RandomGrayscale(p=0.2),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


def probe_pipeline() -> transforms.Compose:
    """Deterministic, for the linear probe that measures the representation."""
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


def build_pretrain_loader(batch_size: int = 512, workers: int = 8) -> DataLoader:
    dataset = CIFAR10(root=DATA_ROOT, train=True, download=False,
                      transform=TwoCropsTransform(contrastive_pipeline()))
    return DataLoader(dataset, batch_size=batch_size, shuffle=True,
                      num_workers=workers, pin_memory=True, drop_last=True)


def build_probe_loaders(batch_size: int = 256, workers: int = 8):
    train_ds = CIFAR10(root=DATA_ROOT, train=True, download=False,
                       transform=probe_pipeline())
    test_ds = CIFAR10(root=DATA_ROOT, train=False, download=False,
                      transform=probe_pipeline())
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, test_loader
