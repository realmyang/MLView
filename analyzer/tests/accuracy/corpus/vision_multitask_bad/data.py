"""Albumentations pipelines that carry the mask and the boxes with the image,
plus a collate that pads a variable number of boxes per image.

Albumentations is the reason this file exists: it is the one augmentation
library that applies a geometric decision to the image, the mask and the
bounding boxes at once, so the three stay consistent.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

import albumentations as A
import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import Dataset

IMAGE_SIZE = 512
MAX_BOXES = 64


def train_augment(size: int = IMAGE_SIZE) -> A.Compose:
    """Geometry and photometry, applied to image + mask + bboxes together."""
    return A.Compose(
        [
            A.LongestMaxSize(max_size=size),
            A.PadIfNeeded(min_height=size, min_width=size,
                          border_mode=cv2.BORDER_CONSTANT, value=0),
            A.HorizontalFlip(p=0.5),
            A.ShiftScaleRotate(shift_limit=0.05, scale_limit=0.2,
                               rotate_limit=15, p=0.7),
            A.RandomBrightnessContrast(p=0.5),
            A.HueSaturationValue(p=0.3),
            A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ToTensorV2(),
        ],
        bbox_params=A.BboxParams(format="pascal_voc", label_fields=["labels"],
                                 min_visibility=0.3),
    )


def eval_augment(size: int = IMAGE_SIZE) -> A.Compose:
    """Resize, pad, normalise. Nothing random."""
    return A.Compose(
        [
            A.LongestMaxSize(max_size=size),
            A.PadIfNeeded(min_height=size, min_width=size,
                          border_mode=cv2.BORDER_CONSTANT, value=0),
            A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
            ToTensorV2(),
        ],
        bbox_params=A.BboxParams(format="pascal_voc", label_fields=["labels"]),
    )


class MultiTaskDataset(Dataset):
    """`<root>/<split>/images`, `.../masks`, `.../boxes.json`."""

    def __init__(self, root: str, split: str = "train", augment=None) -> None:
        self.root = os.path.join(root, split)
        self.augment = augment
        with open(os.path.join(self.root, "boxes.json"), "r",
                  encoding="utf-8") as handle:
            self.records: List[Dict] = json.load(handle)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        record = self.records[index]
        image = cv2.imread(os.path.join(self.root, "images", record["file"]))
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mask = cv2.imread(os.path.join(self.root, "masks", record["mask"]),
                          cv2.IMREAD_GRAYSCALE)
        boxes = np.array(record["boxes"], dtype=np.float32).reshape(-1, 4)
        labels = np.array(record["labels"], dtype=np.int64).reshape(-1)

        if self.augment is not None:
            augmented = self.augment(image=image, mask=mask,
                                     bboxes=boxes.tolist(),
                                     labels=labels.tolist())
            image = augmented["image"]
            mask = augmented["mask"]
            boxes = np.array(augmented["bboxes"], dtype=np.float32).reshape(-1, 4)
            labels = np.array(augmented["labels"], dtype=np.int64).reshape(-1)

        mask_tensor = torch.as_tensor(np.asarray(mask), dtype=torch.float32)
        if mask_tensor.ndim == 2:
            mask_tensor = mask_tensor.unsqueeze(0)
        return {"image": image,
                "mask": mask_tensor / 255.0,
                "boxes": torch.from_numpy(boxes),
                "labels": torch.from_numpy(labels)}


def multitask_collate(batch):
    """Pad every sample to MAX_BOXES; -1 marks a padded class slot."""
    images = torch.stack([item["image"] for item in batch])
    masks = torch.stack([item["mask"] for item in batch])
    boxes = torch.zeros(len(batch), 4, MAX_BOXES)
    classes = torch.full((len(batch), MAX_BOXES), -1, dtype=torch.long)
    for position, item in enumerate(batch):
        count = min(MAX_BOXES, int(item["boxes"].shape[0]))
        if count:
            boxes[position, :, :count] = item["boxes"][:count].transpose(0, 1)
            classes[position, :count] = item["labels"][:count]
    return {"images": images,
            "targets": {"masks": masks, "boxes": boxes, "classes": classes}}


def mask_iou(predicted: torch.Tensor, target: torch.Tensor) -> float:
    intersection = (predicted * target).sum().item()
    union = (predicted + target).clamp(max=1.0).sum().item()
    return intersection / max(1.0, union)
