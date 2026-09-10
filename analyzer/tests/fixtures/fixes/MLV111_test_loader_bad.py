# MLVIEW-EXPECT: MLV111 confidence>=0.7
"""H5: the narrowest edit in the product - one literal replaced by one literal.

The call is spread over two lines and the shuffled keyword is followed by a
trailing comment, so the edit has to replace the range of the `True` node and
nothing around it. A regex over the line would have eaten the comment.
"""
import torch
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset):
    train_ds, test_ds = random_split(dataset, [45000, 5000],
                                     generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=256,
                             shuffle=True)  # ordered predictions, please
    return train_loader, test_loader
