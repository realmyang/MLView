# MLVIEW-EXPECT: MLV114 line=13 confidence>=0.6
"""The evaluation dataset is given the augmenting pipeline, so every validation
pass sees differently cropped and flipped images and the curve moves for reasons
that have nothing to do with the model."""
import torch
import torchvision
from torch.utils.data import DataLoader
from torchvision import transforms

torch.manual_seed(0)
DATA_ROOT = "data/cifar10"

EVAL_TRANSFORM = transforms.Compose([
    transforms.RandomResizedCrop(32),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize((0.5, 0.5, 0.5), (0.25, 0.25, 0.25)),
])

test_ds = torchvision.datasets.CIFAR10(root=DATA_ROOT, train=False, download=False,
                                       transform=EVAL_TRANSFORM)
test_loader = DataLoader(test_ds, batch_size=256, shuffle=False)
