"""Clip sampling for a video classifier (defective twin).

Defect 1: every split gets the training clip transform, so the validation and
test clips are randomly cropped and flipped.
Defect 2 (no rule covers it yet): `_start_index` draws a random offset for
every split, so the same validation video is a different clip each epoch -
the validation curve is measuring clip sampling, not the model.
Defect 3: the training loader is built with `shuffle=False`, and clips are
listed class by class.
Defect 4: the evaluation loaders drop the last partial batch, so the reported
accuracy silently omits up to seven videos per split.
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

CLIP_TRANSFORM = transforms.Compose([
    transforms.RandomResizedCrop(SIDE, scale=(0.6, 1.0), antialias=True),
    transforms.RandomHorizontalFlip(),
    transforms.Normalize(MEAN, STD),
])


class VideoClipDataset(Dataset):
    """One clip per item, shaped (C, T, H, W)."""

    def __init__(self, root: str, split: str, train: bool) -> None:
        self.root = os.path.join(root, split)
        self.train = train
        self.transform = CLIP_TRANSFORM
        self.items: List[Tuple[str, int]] = []
        for label, name in enumerate(sorted(os.listdir(self.root))):
            folder = os.path.join(self.root, name)
            for filename in sorted(os.listdir(folder)):
                self.items.append((os.path.join(folder, filename), label))

    def __len__(self) -> int:
        return len(self.items)

    def _start_index(self, available: int) -> int:
        """Defect 2: a random offset regardless of the split."""
        span = FRAMES * STRIDE
        if available <= span:
            return 0
        return int(torch.randint(0, available - span, (1,)).item())

    def __getitem__(self, index: int):
        path, label = self.items[index]
        frames, _audio, _info = read_video(path, output_format="TCHW")
        start = self._start_index(frames.shape[0])
        picked = frames[start:start + FRAMES * STRIDE:STRIDE].float() / 255.0
        clip = self.transform(picked)
        return clip.permute(1, 0, 2, 3), label


def build_loaders(root: str, batch_size: int = 8, workers: int = 6):
    """Defects 3 and 4."""
    train_ds = VideoClipDataset(root, "train", train=True)
    val_ds = VideoClipDataset(root, "val", train=False)
    test_ds = VideoClipDataset(root, "test", train=False)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=False,
                              num_workers=workers, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True, drop_last=True)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False,
                             num_workers=workers, pin_memory=True, drop_last=True)
    return train_loader, val_loader, test_loader
