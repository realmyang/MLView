"""FixMatch data: one labelled loader, one unlabelled loader that returns two
differently augmented views of the same image.

The weak view decides the pseudo-label; the strong view is what the consistency
loss is trained on. RandAugment therefore belongs in exactly one of the three
pipelines, and the evaluation pipeline has to stay deterministic or the reported
accuracy moves for reasons that have nothing to do with the model.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

CIFAR_MEAN = (0.4914, 0.4822, 0.4465)
CIFAR_STD = (0.2471, 0.2435, 0.2616)


def weak_transform(size: int = 32) -> transforms.Compose:
    """Flip and shift only - weak enough that the pseudo-label is trustworthy."""
    return transforms.Compose([
        transforms.RandomHorizontalFlip(),
        transforms.RandomCrop(size, padding=int(size * 0.125), padding_mode="reflect"),
        transforms.ToTensor(),
        transforms.Normalize(mean=CIFAR_MEAN, std=CIFAR_STD),
    ])


def strong_transform(size: int = 32) -> transforms.Compose:
    """RandAugment plus Cutout - the view the consistency term is trained on."""
    return transforms.Compose([
        transforms.RandomHorizontalFlip(),
        transforms.RandomCrop(size, padding=int(size * 0.125), padding_mode="reflect"),
        transforms.RandAugment(num_ops=2, magnitude=10),
        transforms.ToTensor(),
        transforms.Normalize(mean=CIFAR_MEAN, std=CIFAR_STD),
        transforms.RandomErasing(p=0.5, scale=(0.02, 0.15)),
    ])


def eval_transform() -> transforms.Compose:
    """Deterministic: no flip, no crop, no RandAugment."""
    return transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=CIFAR_MEAN, std=CIFAR_STD),
    ])


class ImageListDataset(Dataset):
    """`(path, label)` rows; label -1 marks an unlabelled row."""

    def __init__(self, rows: List[Tuple[str, int]], transform=None) -> None:
        self.rows = list(rows)
        self.transform = transform

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        path, label = self.rows[index]
        image = Image.open(path).convert("RGB")
        if self.transform is not None:
            image = self.transform(image)
        return image, label


class TwoViewDataset(Dataset):
    """Returns `(weak, strong)` for the same image - FixMatch's whole trick."""

    def __init__(self, rows: List[Tuple[str, int]], weak, strong) -> None:
        self.rows = list(rows)
        self.weak = weak
        self.strong = strong

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        path, _label = self.rows[index]
        image = Image.open(path).convert("RGB")
        return self.weak(image), self.strong(image)


def read_manifest(path: str) -> List[Tuple[str, int]]:
    rows: List[Tuple[str, int]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            name, _, label = line.partition("\t")
            rows.append((name, int(label) if label else -1))
    return rows


def stratified_label_subset(rows: List[Tuple[str, int]], per_class: int,
                            num_classes: int, rng: np.random.Generator
                            ) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    """`per_class` labelled rows per class; everything else becomes unlabelled.

    The unlabelled pool keeps its rows but drops its labels, which is what the
    benchmark protocol asks for: the labels exist on disk and are never read.
    """
    labelled: List[Tuple[str, int]] = []
    taken = set()
    for klass in range(num_classes):
        candidates = [i for i, (_p, y) in enumerate(rows) if y == klass]
        chosen = rng.permutation(len(candidates))[:per_class]
        for offset in chosen:
            index = candidates[int(offset)]
            taken.add(index)
            labelled.append(rows[index])
    unlabelled = [(path, -1) for i, (path, _y) in enumerate(rows) if i not in taken]
    return labelled, unlabelled


def interleave(batch: torch.Tensor, size: int) -> torch.Tensor:
    """Keep the BatchNorm statistics of the three sub-batches comparable."""
    shape = batch.shape
    return batch.reshape(-1, size, *shape[1:]).transpose(0, 1).reshape(-1, *shape[1:])
