"""ROB-15. One parallel assignment, and the training loop becomes an eval loop.

Everything here is correct PyTorch and the loop is unambiguously a *training*
loop: it zeroes the gradients, calls `backward()` and steps the optimizer. The
only thing that is unusual is line 20 --

    opt, crit = torch.optim.Adam(model.parameters()), nn.CrossEntropyLoss()

-- the ordinary Python way to bind two values on one line. Splitting it into
two statements changes nothing about the program and everything about the
analysis.

Observed (`--dataflow local` and `ip`, identical)::

    nodes         6      (9 with the two statements written apart)
    loops         eval_loop at line 22
    stages[eval]  present: true
    issues        MLV601 only

Expected: a `train_loop`, `stages[eval].present == false` on a file with no
evaluation in it, and the `zero_grad()` / `backward()` / `step()` op nodes.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(ds):
    model = nn.Linear(16, 3)
    opt, crit = torch.optim.Adam(model.parameters()), nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
