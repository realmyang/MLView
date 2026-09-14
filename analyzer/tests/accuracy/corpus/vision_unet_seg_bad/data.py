"""Segmentation data (defective twin).

Defect 1: VAL_AUGMENTATION still carries the horizontal flip and the
brightness/contrast jitter, so validation IoU moves between epochs for reasons
that have nothing to do with the weights.
Defect 2: the validation split is carved out with `random_split` and no
generator, so it is a different subset on every run.
Defect 3: the training loader does not shuffle.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import albumentations as A
import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import DataLoader, Dataset, random_split

IMAGE_SIZE = 512
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
SEED = 2024

TRAIN_AUGMENTATION = A.Compose([
    A.RandomResizedCrop(height=IMAGE_SIZE, width=IMAGE_SIZE, scale=(0.5, 1.0)),
    A.HorizontalFlip(p=0.5),
    A.ShiftScaleRotate(shift_limit=0.05, scale_limit=0.1, rotate_limit=15, p=0.5),
    A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
    A.Normalize(mean=MEAN, std=STD),
    ToTensorV2(),
])

VAL_AUGMENTATION = A.Compose([
    A.Resize(height=IMAGE_SIZE, width=IMAGE_SIZE),
    A.HorizontalFlip(p=0.5),
    A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
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


def build_loaders(root: str, batch_size: int = 4, workers: int = 4):
    """Defects 2 and 3: an unseeded split and a training loader in file order."""
    full = SegmentationFolder(os.path.join(root, "train", "images"),
                              os.path.join(root, "train", "masks"),
                              TRAIN_AUGMENTATION)
    test_ds = SegmentationFolder(os.path.join(root, "test", "images"),
                                 os.path.join(root, "test", "masks"),
                                 VAL_AUGMENTATION)
    train_ds, val_ds = random_split(full, [0.9, 0.1])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=False,
                              num_workers=workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, val_loader, test_loader
