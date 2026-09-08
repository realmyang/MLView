# MLVIEW-EXPECT: MLV111 line=11 confidence>=0.6 severity=low
"""The test loader shuffles, so predictions no longer match dataset order."""
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset):
    train_ds, test_ds = random_split(dataset, [45000, 5000],
                                     generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=256, shuffle=True)
    return train_loader, test_loader
