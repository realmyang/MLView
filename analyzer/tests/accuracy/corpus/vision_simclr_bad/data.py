"""SimCLR views (defective twin).

Defect 1 (no rule covers it yet): `TwoCropsTransform` applies the pipeline
once and returns the same tensor twice, so the two "views" are identical and
the contrastive task is trivially solvable - the loss falls to zero and the
representation learns nothing.
Defect 2: the linear-probe pipeline is the contrastive pipeline, so the frozen
encoder is probed on randomly cropped, colour-jittered, grayscaled images.
Defect 3: the pre-training loader does not shuffle.
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

CONTRASTIVE_PIPELINE = transforms.Compose([
    transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.2, 1.0)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomApply([transforms.ColorJitter(0.4, 0.4, 0.4, 0.1)], p=0.8),
    transforms.RandomGrayscale(p=0.2),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])

PROBE_PIPELINE = transforms.Compose([
    transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.2, 1.0)),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomGrayscale(p=0.2),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])


class TwoCropsTransform:
    """Defect 1: one draw, returned twice."""

    def __init__(self, pipeline: transforms.Compose) -> None:
        self.pipeline = pipeline

    def __call__(self, image) -> Tuple[torch.Tensor, torch.Tensor]:
        view = self.pipeline(image)
        return view, view


def build_pretrain_loader(batch_size: int = 512, workers: int = 8) -> DataLoader:
    """Defect 3: shuffle=False on the pre-training loader."""
    dataset = CIFAR10(root=DATA_ROOT, train=True, download=False,
                      transform=TwoCropsTransform(CONTRASTIVE_PIPELINE))
    return DataLoader(dataset, batch_size=batch_size, shuffle=False,
                      num_workers=workers, pin_memory=True, drop_last=True)


def build_probe_loaders(batch_size: int = 256, workers: int = 8):
    """Defect 2: the probe and test loaders use the augmented pipeline."""
    train_ds = CIFAR10(root=DATA_ROOT, train=True, download=False,
                       transform=PROBE_PIPELINE)
    test_ds = CIFAR10(root=DATA_ROOT, train=False, download=False,
                      transform=PROBE_PIPELINE)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, test_loader
