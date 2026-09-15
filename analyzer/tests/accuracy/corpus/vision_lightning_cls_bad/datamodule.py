"""The LightningDataModule (defective twin).

Defect 1: `ImageDataModule.__init__` never calls `super().__init__()`, so the
Lightning bookkeeping the base class sets up is missing and
`save_hyperparameters()` fails on the first line that uses it.
Defect 2: the evaluation pipeline is the augmented pipeline.
Defect 3: the validation loader shuffles.
"""

from __future__ import annotations

import os

import pytorch_lightning as pl
import torch
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import ImageFolder

IMAGE_SIZE = 224
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


class ImageDataModule(pl.LightningDataModule):
    """Defect 1: no super().__init__()."""

    def __init__(self, root: str = "data/pets", batch_size: int = 32,
                 workers: int = 8) -> None:
        self.root = root
        self.batch_size = batch_size
        self.workers = workers
        self.train_ds = None
        self.val_ds = None
        self.test_ds = None

    def train_transform(self) -> transforms.Compose:
        return transforms.Compose([
            transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.6, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(0.2, 0.2, 0.2),
            transforms.ToTensor(),
            transforms.Normalize(MEAN, STD),
        ])

    def setup(self, stage: str = None) -> None:
        """Defect 2: one pipeline for all three splits."""
        self.train_ds = ImageFolder(os.path.join(self.root, "train"),
                                    transform=self.train_transform())
        self.val_ds = ImageFolder(os.path.join(self.root, "val"),
                                  transform=self.train_transform())
        self.test_ds = ImageFolder(os.path.join(self.root, "test"),
                                   transform=self.train_transform())

    def train_dataloader(self) -> DataLoader:
        return DataLoader(self.train_ds, batch_size=self.batch_size, shuffle=True,
                          num_workers=self.workers, pin_memory=True,
                          drop_last=True, persistent_workers=True)

    def val_dataloader(self) -> DataLoader:
        """Defect 3: shuffle=True on the validation loader."""
        return DataLoader(self.val_ds, batch_size=self.batch_size, shuffle=True,
                          num_workers=self.workers, pin_memory=True)

    def test_dataloader(self) -> DataLoader:
        return DataLoader(self.test_ds, batch_size=self.batch_size, shuffle=False,
                          num_workers=self.workers, pin_memory=True)
