# MLVIEW-EXPECT: MLV602 confidence>=0.7
"""H5, withheld: the module imports `random_split` but never binds `torch`.

The only documented fix for an unseeded `random_split` is
`generator=torch.Generator().manual_seed(42)`, which needs the name `torch` in
this file. Adding the import too would be a second edit in a second place, and
this feature deliberately does not do that - so the finding ships with its
prose hint and no edit at all.

`samples/vision_pipeline/data.py` has exactly this shape, which is why the demo
lists one MLV602 fix and not two.
"""
from torch.utils.data import TensorDataset, random_split


def split(dataset: TensorDataset):
    train_ds, val_ds = random_split(dataset, [45000, 5000])
    return train_ds, val_ds
