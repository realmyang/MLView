"""Datasets, transforms and loaders - corrected twin.

Fix 15 (MLV602): the split takes an explicit generator.
Fix  7 (MLV110): the training loader shuffles.
Fix  8 (MLV112): nothing is built at import time, so spawn can re-import safely.
Fix 12 (MLV111): the test loader keeps dataset order.
"""

import torch
import torchvision
from torch.utils.data import DataLoader, random_split
from torchvision import transforms

from config import (BATCH_SIZE, DATA_ROOT, EVAL_BATCH_SIZE, NUM_WORKERS, SEED,
                    TRAIN_SIZE, VAL_SIZE)

TRAIN_TRANSFORM = transforms.Compose([
    transforms.RandomCrop(32, padding=4),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
])
EVAL_TRANSFORM = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2470, 0.2435, 0.2616)),
])


def build_loaders():
    """Build the three loaders. Called from the entrypoint, never on import."""
    full_train = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=True, download=False,
                                              transform=TRAIN_TRANSFORM)
    test_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=False, download=False,
                                           transform=EVAL_TRANSFORM)
    generator = torch.Generator().manual_seed(SEED)
    train_ds, val_ds = random_split(full_train, [TRAIN_SIZE, VAL_SIZE],
                                    generator=generator)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=NUM_WORKERS)
    val_loader = DataLoader(val_ds, batch_size=EVAL_BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=EVAL_BATCH_SIZE, shuffle=False)
    return train_loader, val_loader, test_loader
