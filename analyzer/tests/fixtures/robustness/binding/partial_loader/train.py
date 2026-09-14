"""ROB-17. `functools.partial(DataLoader, ...)`, and the data stage is declared
absent - with an empty `diagnostics` list.

`partial` is how a project pins the loader keywords once and reuses them, and
it is the one factory shape that leaves no trace: a workspace helper function
(`def make_loader(d): return DataLoader(...)`) keeps the loader, a `lambda`
keeps it and raises `unresolved_callee`, a dict lookup loses it but raises
`unresolved_callee` - `functools.partial` loses it and raises nothing.

Observed::

    stages[data].present   false
    diagnostics            []
    answers.dataEntry      "No data entry was detected: nothing in this
                            workspace builds a dataset or a loader, so MLView
                            could not determine where the data comes from."

That sentence is a claim about a file whose third line imports `DataLoader` and
whose sixth builds one. CONTRACTS 11.23 A1-A8: no emitter may claim a stage is
absent without qualification. Expected: the loader in the data lane, or at
minimum an `unresolved_callee` diagnostic and the *unverified* qualifier.
"""
from functools import partial

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

make_loader = partial(DataLoader, batch_size=8, shuffle=True)


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = make_loader(ds)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
