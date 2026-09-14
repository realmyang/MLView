"""The detection dataset, its ragged collate and the three loaders.

Detection targets are ragged - image *i* has n_i boxes - so the batch cannot be
stacked by the default collate. `detection_collate` keeps the per-image lists
and stacks only the images.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.io import read_image

IMAGE_SIZE = 640
SEED = 7


class CocoStyleDetection(Dataset):
    """Reads an annotation JSON of {image, boxes, labels} records."""

    def __init__(self, root: str, annotation_file: str, train: bool) -> None:
        with open(annotation_file, "r", encoding="utf-8") as handle:
            self.records = json.load(handle)
        self.root = root
        self.train = train
        self.normalize = transforms.Normalize((0.485, 0.456, 0.406),
                                              (0.229, 0.224, 0.225))
        self.resize = transforms.Resize((IMAGE_SIZE, IMAGE_SIZE), antialias=True)

    def __len__(self) -> int:
        return len(self.records)

    def _augment(self, image: torch.Tensor, boxes: torch.Tensor):
        """Horizontal flip - training only, and the boxes flip with the pixels."""
        if torch.rand(()) < 0.5:
            image = torch.flip(image, dims=[-1])
            width = image.shape[-1]
            flipped = boxes.clone()
            flipped[:, 0] = width - boxes[:, 2]
            flipped[:, 2] = width - boxes[:, 0]
            boxes = flipped
        return image, boxes

    def __getitem__(self, index: int):
        record = self.records[index]
        image = read_image(os.path.join(self.root, record["image"])).float() / 255.0
        boxes = torch.tensor(record["boxes"], dtype=torch.float32).reshape(-1, 4)
        labels = torch.tensor(record["labels"], dtype=torch.long).reshape(-1)
        image = self.resize(image)
        if self.train:
            image, boxes = self._augment(image, boxes)
        image = self.normalize(image)
        return image, {"boxes": boxes, "labels": labels}


def detection_collate(batch: List[Tuple[torch.Tensor, dict]]):
    """Stack the images, keep the targets as a list of dicts."""
    images = torch.stack([item[0] for item in batch], dim=0)
    targets = [item[1] for item in batch]
    return images, targets


def build_loaders(root: str, annotations: str, batch_size: int = 8,
                  workers: int = 4):
    """Train / val / test loaders over three annotation files."""
    train_ds = CocoStyleDetection(root, os.path.join(annotations, "train.json"),
                                  train=True)
    val_ds = CocoStyleDetection(root, os.path.join(annotations, "val.json"),
                                train=False)
    test_ds = CocoStyleDetection(root, os.path.join(annotations, "test.json"),
                                 train=False)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, collate_fn=detection_collate,
                              pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, collate_fn=detection_collate)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, collate_fn=detection_collate)
    return train_loader, val_loader, test_loader


def to_device(images: torch.Tensor, targets: List[dict], device: torch.device):
    """Images stack straight onto the device; targets move field by field."""
    images = images.to(device, non_blocking=True)
    moved = [{"boxes": t["boxes"].to(device), "labels": t["labels"].to(device)}
             for t in targets]
    return images, moved
