"""Clip sampling for a video classifier.

A clip is `FRAMES` frames at `STRIDE` spacing. Training takes a random start
offset; evaluation takes the centre clip, so the same video always produces
the same tensor and a per-video score is comparable across epochs.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import torch
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.io import read_video

FRAMES = 16
STRIDE = 2
SIDE = 112
MEAN = (0.43216, 0.394666, 0.37645)
STD = (0.22803, 0.22145, 0.216989)
SEED = 5150


def train_clip_transform() -> transforms.Compose:
    """Applied per frame: random crop, flip, normalise."""
    return transforms.Compose([
        transforms.RandomResizedCrop(SIDE, scale=(0.6, 1.0), antialias=True),
        transforms.RandomHorizontalFlip(),
        transforms.Normalize(MEAN, STD),
    ])


def eval_clip_transform() -> transforms.Compose:
    """Deterministic centre crop and the same normalisation."""
    return transforms.Compose([
        transforms.Resize(SIDE + 16, antialias=True),
        transforms.CenterCrop(SIDE),
        transforms.Normalize(MEAN, STD),
    ])


class VideoClipDataset(Dataset):
    """One clip per item, shaped (C, T, H, W)."""

    def __init__(self, root: str, split: str, train: bool) -> None:
        self.root = os.path.join(root, split)
        self.train = train
        self.transform = train_clip_transform() if train else eval_clip_transform()
        self.items: List[Tuple[str, int]] = []
        for label, name in enumerate(sorted(os.listdir(self.root))):
            folder = os.path.join(self.root, name)
            for filename in sorted(os.listdir(folder)):
                self.items.append((os.path.join(folder, filename), label))

    def __len__(self) -> int:
        return len(self.items)

    def _start_index(self, available: int) -> int:
        """Random offset while training, the centre clip while evaluating."""
        span = FRAMES * STRIDE
        if available <= span:
            return 0
        if self.train:
            return int(torch.randint(0, available - span, (1,)).item())
        return (available - span) // 2

    def __getitem__(self, index: int):
        path, label = self.items[index]
        frames, _audio, _info = read_video(path, output_format="TCHW")
        start = self._start_index(frames.shape[0])
        picked = frames[start:start + FRAMES * STRIDE:STRIDE].float() / 255.0
        clip = self.transform(picked)
        return clip.permute(1, 0, 2, 3), label


def build_loaders(root: str, batch_size: int = 8, workers: int = 6):
    train_ds = VideoClipDataset(root, "train", train=True)
    val_ds = VideoClipDataset(root, "val", train=False)
    test_ds = VideoClipDataset(root, "test", train=False)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True)
    return train_loader, val_loader, test_loader
