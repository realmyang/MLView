# MLVIEW-EXPECT-NONE: MLV111
"""The trap: shuffle=True everywhere it belongs. The training loader shuffles
(and must not be mistaken for an evaluation loader just because it shuffles),
a generic `loader` over untagged data shuffles, and only the loaders over the
held-out split are ordered."""
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset, extra: TensorDataset):
    train_ds, val_ds, test_ds = random_split(
        dataset, [40000, 5000, 5000], generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
    loader = DataLoader(extra, batch_size=64, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=256, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=256)
    return train_loader, loader, val_loader, test_loader
