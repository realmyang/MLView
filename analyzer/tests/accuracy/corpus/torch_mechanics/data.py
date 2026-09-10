"""Datasets, transforms and loaders for the CIFAR-shaped classifier.

Planted defect: the evaluation dataset is handed a pipeline that still contains
RandomResizedCrop and RandomHorizontalFlip, so every validation pass sees a
different crop of every image and the curve moves for reasons that have nothing
to do with the model.
"""
from __future__ import annotations

import torchvision
from torch.utils.data import DataLoader
from torchvision import transforms

DATA_ROOT = "data/cifar10"
BATCH_SIZE = 128
EVAL_BATCH_SIZE = 256

TRAIN_TRANSFORM = transforms.Compose([
    transforms.RandomResizedCrop(32, scale=(0.7, 1.0)),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
])
EVAL_TRANSFORM = transforms.Compose([
    transforms.RandomResizedCrop(32, scale=(0.7, 1.0)),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
])


def build_loaders():
    train_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=True,
                                            download=False,
                                            transform=TRAIN_TRANSFORM)
    test_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=False,
                                           download=False,
                                           transform=EVAL_TRANSFORM)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=EVAL_BATCH_SIZE, shuffle=False)
    return train_loader, test_loader
