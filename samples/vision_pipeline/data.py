"""Datasets, transforms and loaders.

Planted here: MLV602 (random_split without a generator), MLV110 (the training
loader never shuffles), MLV112 (worker processes with no __main__ guard) and
MLV111 (the test loader shuffles).
"""

import torchvision
from torch.utils.data import DataLoader, random_split
from torchvision import transforms

from config import (BATCH_SIZE, DATA_ROOT, EVAL_BATCH_SIZE, NUM_WORKERS, TRAIN_SIZE,
                    VAL_SIZE)

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

full_train = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=True, download=False,
                                          transform=TRAIN_TRANSFORM)
test_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=False, download=False,
                                       transform=EVAL_TRANSFORM)

train_ds, val_ds = random_split(full_train, [TRAIN_SIZE, VAL_SIZE])

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, num_workers=NUM_WORKERS)
val_loader = DataLoader(val_ds, batch_size=EVAL_BATCH_SIZE, shuffle=False)
test_loader = DataLoader(test_ds, batch_size=EVAL_BATCH_SIZE, shuffle=True)
