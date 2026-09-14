"""Segmentation data: albumentations pipelines, dataset and loaders.

The training pipeline is geometric + photometric; the validation pipeline is a
deterministic resize and the same normalisation, so the mask a metric is
computed against is always the same mask.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import albumentations as A
import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import DataLoader, Dataset

IMAGE_SIZE = 512
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
SEED = 2024


def train_augmentation() -> A.Compose:
    """Random crop, flips, rotation and brightness - training only."""
    return A.Compose([
        A.RandomResizedCrop(height=IMAGE_SIZE, width=IMAGE_SIZE, scale=(0.5, 1.0)),
        A.HorizontalFlip(p=0.5),
        A.ShiftScaleRotate(shift_limit=0.05, scale_limit=0.1, rotate_limit=15, p=0.5),
        A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
        A.Normalize(mean=MEAN, std=STD),
        ToTensorV2(),
    ])


def eval_augmentation() -> A.Compose:
    """Deterministic: resize and normalise, nothing random."""
    return A.Compose([
        A.Resize(height=IMAGE_SIZE, width=IMAGE_SIZE),
        A.Normalize(mean=MEAN, std=STD),
        ToTensorV2(),
    ])


class SegmentationFolder(Dataset):
    """Paired image/mask folders; the mask is a single-channel 0/1 PNG."""

    def __init__(self, image_dir: str, mask_dir: str, transform: A.Compose) -> None:
        self.image_dir = image_dir
        self.mask_dir = mask_dir
        self.transform = transform
        self.names: List[str] = sorted(os.listdir(image_dir))

    def __len__(self) -> int:
        return len(self.names)

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor]:
        name = self.names[index]
        image = cv2.cvtColor(cv2.imread(os.path.join(self.image_dir, name)),
                             cv2.COLOR_BGR2RGB)
        mask = cv2.imread(os.path.join(self.mask_dir, name), cv2.IMREAD_GRAYSCALE)
        mask = (mask > 127).astype(np.float32)
        augmented = self.transform(image=image, mask=mask)
        return augmented["image"], augmented["mask"].unsqueeze(0)


def build_datasets(root: str):
    """Three folders, two transform pipelines."""
    train_ds = SegmentationFolder(os.path.join(root, "train", "images"),
                                  os.path.join(root, "train", "masks"),
                                  train_augmentation())
    val_ds = SegmentationFolder(os.path.join(root, "val", "images"),
                                os.path.join(root, "val", "masks"),
                                eval_augmentation())
    test_ds = SegmentationFolder(os.path.join(root, "test", "images"),
                                 os.path.join(root, "test", "masks"),
                                 eval_augmentation())
    return train_ds, val_ds, test_ds


def build_loaders(root: str, batch_size: int = 4, workers: int = 4):
    train_ds, val_ds, test_ds = build_datasets(root)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, val_loader, test_loader
