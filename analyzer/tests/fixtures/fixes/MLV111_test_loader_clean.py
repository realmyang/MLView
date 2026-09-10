# MLVIEW-EXPECT-NONE: MLV111
"""H5: the clean twin of `MLV111_test_loader_bad.py` - the evaluation loader is
already ordered, comment and all, and the training loader still shuffles.
"""
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset):
    train_ds, test_ds = random_split(dataset, [45000, 5000],
                                     generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=256,
                             shuffle=False)  # ordered predictions, please
    return train_loader, test_loader
