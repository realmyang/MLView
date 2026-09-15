"""The detection dataset and its loaders (defective twin).

Defect B: the three loaders are built at import time with four worker
processes each and the module has no `__main__` guard, so on spawn platforms
every worker re-imports this module and builds three more loaders.
Defect C: the training loader does not shuffle.
Defect D: the validation loader does.
Defect E (no rule covers it yet): `_augment` ignores `self.train`, so the
random horizontal flip is applied to the validation and test images too.
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
DATA_ROOT = "data/coco"
ANNOTATIONS = "data/coco/annotations"
BATCH_SIZE = 8
WORKERS = 4


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
        """Defect E: no `self.train` check, so this runs on every split."""
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
        image, boxes = self._augment(image, boxes)
        image = self.normalize(image)
        return image, {"boxes": boxes, "labels": labels}


def detection_collate(batch: List[Tuple[torch.Tensor, dict]]):
    """Stack the images, keep the targets as a list of dicts."""
    images = torch.stack([item[0] for item in batch], dim=0)
    targets = [item[1] for item in batch]
    return images, targets


TRAIN_DS = CocoStyleDetection(DATA_ROOT, os.path.join(ANNOTATIONS, "train.json"),
                              train=True)
VAL_DS = CocoStyleDetection(DATA_ROOT, os.path.join(ANNOTATIONS, "val.json"),
                            train=False)
TEST_DS = CocoStyleDetection(DATA_ROOT, os.path.join(ANNOTATIONS, "test.json"),
                             train=False)

TRAIN_LOADER = DataLoader(TRAIN_DS, batch_size=BATCH_SIZE, shuffle=False,
                          num_workers=WORKERS, collate_fn=detection_collate,
                          pin_memory=True, drop_last=True)
VAL_LOADER = DataLoader(VAL_DS, batch_size=BATCH_SIZE, shuffle=True,
                        num_workers=WORKERS, collate_fn=detection_collate)
TEST_LOADER = DataLoader(TEST_DS, batch_size=BATCH_SIZE, shuffle=False,
                         num_workers=WORKERS, collate_fn=detection_collate)


def to_device(images: torch.Tensor, targets: List[dict], device: torch.device):
    """Images stack straight onto the device; targets move field by field."""
    images = images.to(device, non_blocking=True)
    moved = [{"boxes": t["boxes"].to(device), "labels": t["labels"].to(device)}
             for t in targets]
    return images, moved
