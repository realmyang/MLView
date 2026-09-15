"""Paired low-/high-resolution patches, cropped on the fly.

The augmentation is geometric and is applied to **both** members of the pair
with the same parameters - a super-resolution pipeline that flips only the
target teaches the generator to hallucinate a mirror image. The evaluation
pipeline does nothing but convert to a tensor: PSNR on a randomly cropped patch
is not PSNR on the image.
"""

from __future__ import annotations

import os
import random
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms
from torchvision.transforms import functional as TF


def train_pipeline(patch: int) -> transforms.Compose:
    """Colour jitter on the LOW-resolution member only, built once here."""
    return transforms.Compose([
        transforms.ColorJitter(brightness=0.05, contrast=0.05, saturation=0.05),
        transforms.ToTensor(),
    ])


def eval_pipeline() -> transforms.Compose:
    return transforms.Compose([transforms.ToTensor()])


class PairedPatchDataset(Dataset):
    """`<root>/hr/*.png` with the low-resolution twin derived by bicubic down."""

    def __init__(self, root: str, scale: int = 4, patch: int = 128,
                 pipeline=None, train: bool = True) -> None:
        self.root = root
        self.scale = scale
        self.patch = patch
        self.pipeline = pipeline
        self.train = train
        self.files = self._index(os.path.join(root, "hr"))

    @staticmethod
    def _index(folder: str) -> List[str]:
        return [os.path.join(folder, name) for name in sorted(os.listdir(folder))
                if name.lower().endswith((".png", ".jpg", ".jpeg"))]

    def __len__(self) -> int:
        return len(self.files)

    def _paired_crop(self, image: Image.Image) -> Tuple[Image.Image, Image.Image]:
        width, height = image.size
        size = self.patch
        left = random.randint(0, max(0, width - size))
        top = random.randint(0, max(0, height - size))
        high = image.crop((left, top, left + size, top + size))
        low = high.resize((size // self.scale, size // self.scale), Image.BICUBIC)
        return low, high

    def _center_crop(self, image: Image.Image) -> Tuple[Image.Image, Image.Image]:
        size = self.patch
        high = TF.center_crop(image, [size, size])
        low = high.resize((size // self.scale, size // self.scale), Image.BICUBIC)
        return low, high

    def __getitem__(self, index: int):
        image = Image.open(self.files[index]).convert("RGB")
        if self.train:
            low, high = self._paired_crop(image)
            # the same geometric decision is applied to both members
            if random.random() < 0.5:
                low, high = TF.hflip(low), TF.hflip(high)
            rotations = random.randint(0, 3)
            if rotations:
                low = TF.rotate(low, 90 * rotations)
                high = TF.rotate(high, 90 * rotations)
        else:
            low, high = self._center_crop(image)
        if self.pipeline is not None:
            low = self.pipeline(low)
        else:
            low = TF.to_tensor(low)
        return low, TF.to_tensor(high)


def bicubic_baseline(low: torch.Tensor, scale: int) -> torch.Tensor:
    """The number every super-resolution table is compared against."""
    return torch.nn.functional.interpolate(low, scale_factor=scale,
                                           mode="bicubic", align_corners=False)


def tile_image(image: torch.Tensor, tile: int, overlap: int) -> List[torch.Tensor]:
    """Split a large test image so a 4x model fits in memory."""
    tiles: List[torch.Tensor] = []
    _, _, height, width = image.shape
    step = max(1, tile - overlap)
    for top in range(0, height, step):
        for left in range(0, width, step):
            tiles.append(image[:, :, top:top + tile, left:left + tile])
    return tiles


def manifest_stats(root: str) -> dict:
    files = PairedPatchDataset._index(os.path.join(root, "hr"))
    sizes = np.array([os.path.getsize(path) for path in files], dtype=np.float64)
    return {"count": int(sizes.size),
            "mean_bytes": float(sizes.mean()) if sizes.size else 0.0}
