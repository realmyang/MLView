"""Dataset construction for the shared vision library.

Correct on purpose: the training transform augments, the evaluation transform
does not, the split is seeded, and the evaluation loader does not shuffle.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader, random_split
from torchvision import transforms
from torchvision.datasets import ImageFolder

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
SEED = 4242


def train_transform(size: int = 224) -> transforms.Compose:
    return transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.7, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(0.2, 0.2, 0.2),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


def eval_transform(size: int = 224) -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(size + 32),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(MEAN, STD),
    ])


def build_loaders(root: str, batch_size: int = 64, workers: int = 4,
                  val_fraction: float = 0.2):
    train_all = ImageFolder(root, transform=train_transform())
    eval_all = ImageFolder(root, transform=eval_transform())

    generator = torch.Generator().manual_seed(SEED)
    count = len(train_all)
    val_count = int(count * val_fraction)
    indices = torch.randperm(count, generator=generator).tolist()
    val_indices = indices[:val_count]
    train_indices = indices[val_count:]

    train_set = torch.utils.data.Subset(train_all, train_indices)
    val_set = torch.utils.data.Subset(eval_all, val_indices)

    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              num_workers=workers, drop_last=True,
                              pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False,
                            num_workers=workers, pin_memory=True)
    return train_loader, val_loader


def split_dataset(dataset, val_fraction: float = 0.2):
    """Kept for the notebooks, which call it directly."""
    generator = torch.Generator().manual_seed(SEED)
    val_count = int(len(dataset) * val_fraction)
    return random_split(dataset, [len(dataset) - val_count, val_count],
                        generator=generator)
