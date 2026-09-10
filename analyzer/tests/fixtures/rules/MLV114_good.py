# MLVIEW-EXPECT-NONE: MLV114
"""The trap: an augmenting pipeline and an evaluation loader in the same module,
correctly kept apart - the random crops go to the training dataset and the
evaluation dataset gets a deterministic Resize / ToTensor / Normalize pipeline."""
import torch
import torchvision
from torch.utils.data import DataLoader
from torchvision import transforms

torch.manual_seed(0)
DATA_ROOT = "data/cifar10"

TRAIN_TRANSFORM = transforms.Compose([
    transforms.RandomResizedCrop(32),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
])
EVAL_TRANSFORM = transforms.Compose([
    transforms.Resize(32),
    transforms.ToTensor(),
])

train_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=True, download=False,
                                        transform=TRAIN_TRANSFORM)
test_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=False, download=False,
                                       transform=EVAL_TRANSFORM)
train_loader = DataLoader(train_ds, batch_size=128, shuffle=True)
test_loader = DataLoader(test_ds, batch_size=256, shuffle=False)
