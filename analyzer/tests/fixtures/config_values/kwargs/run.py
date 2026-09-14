"""`shuffle=` out of a container, on both sides of the argument.

Before ANA-10 `CallSite.kwargs` only ever held literals written at the call
site, so MLV110 reported **"shuffle=unset (defaults to False)"** on the training
loader - a false statement about a correct program, at `likely` - and MLV111
could not see the evaluation loader shuffling at all.
"""
from __future__ import annotations

from torch.utils.data import DataLoader, TensorDataset

CFG = {"shuffle": True}

train_ds = TensorDataset()
val_ds = TensorDataset()

train_loader = DataLoader(train_ds, shuffle=CFG["shuffle"])
val_loader = DataLoader(val_ds, shuffle=CFG["shuffle"])

for epoch in range(2):
    for x, y in train_loader:
        pass

for x, y in val_loader:
    pass
