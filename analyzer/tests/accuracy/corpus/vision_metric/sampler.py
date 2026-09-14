"""The P x K batch sampler metric learning needs, and the two transform
pipelines.

A batch-hard triplet miner is only meaningful if every batch contains several
images of each of several identities, which is what `PKSampler` guarantees. It
is passed as `batch_sampler=`, so the loader takes neither `batch_size` nor
`shuffle` - the sampler owns both, and it shuffles.
"""

from __future__ import annotations

import os
import random
from typing import Dict, Iterator, List, Sequence

import torch
from PIL import Image
from torch.utils.data import Dataset, Sampler
from torchvision import transforms

IMAGE_SIZE = (256, 128)
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def train_transform() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(IMAGE_SIZE),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.Pad(10),
        transforms.RandomCrop(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(mean=MEAN, std=STD),
        transforms.RandomErasing(p=0.5, value="random"),
    ])


def eval_transform() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(IMAGE_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(mean=MEAN, std=STD),
    ])


class IdentityDataset(Dataset):
    """`<root>/<split>/<identity>/<image>.jpg`."""

    def __init__(self, root: str, split: str = "train", transform=None) -> None:
        self.root = os.path.join(root, split)
        self.transform = transform
        self.items: List[str] = []
        self.labels: List[int] = []
        self.identity_to_index: Dict[str, int] = {}
        for identity in sorted(os.listdir(self.root)):
            folder = os.path.join(self.root, identity)
            if not os.path.isdir(folder):
                continue
            index = self.identity_to_index.setdefault(identity,
                                                      len(self.identity_to_index))
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith((".jpg", ".png")):
                    self.items.append(os.path.join(folder, name))
                    self.labels.append(index)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int):
        image = Image.open(self.items[index]).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, self.labels[index]


class PKSampler(Sampler):
    """P identities x K images per batch, reshuffled every epoch."""

    def __init__(self, labels: Sequence[int], identities: int = 16,
                 per_identity: int = 4, seed: int = 0) -> None:
        super().__init__(None)
        self.labels = list(labels)
        self.identities = identities
        self.per_identity = per_identity
        self.random = random.Random(seed)
        self.by_identity: Dict[int, List[int]] = {}
        for position, label in enumerate(self.labels):
            self.by_identity.setdefault(int(label), []).append(position)
        self.length = max(1, len(self.labels) // (identities * per_identity))

    def __len__(self) -> int:
        return self.length

    def __iter__(self) -> Iterator[List[int]]:
        keys = list(self.by_identity)
        for _ in range(self.length):
            chosen = self.random.sample(keys, min(self.identities, len(keys)))
            batch: List[int] = []
            for key in chosen:
                pool = self.by_identity[key]
                if len(pool) >= self.per_identity:
                    batch.extend(self.random.sample(pool, self.per_identity))
                else:
                    batch.extend(self.random.choices(pool, k=self.per_identity))
            yield batch


def identity_histogram(labels: Sequence[int]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for label in labels:
        counts[int(label)] = counts.get(int(label), 0) + 1
    return counts


def camera_of(path: str) -> int:
    """Market-1501 encodes the camera in the filename: 0001_c3s1_...jpg."""
    stem = os.path.basename(path)
    parts = stem.split("_")
    if len(parts) > 1 and parts[1].startswith("c"):
        return int(parts[1][1])
    return -1
