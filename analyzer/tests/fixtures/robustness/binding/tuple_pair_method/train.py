"""ROB-15, the shape a real project actually writes: a Trainer class whose
`__init__` binds the optimizer and the criterion on one line.

    self.opt, self.crit = torch.optim.Adam(...), nn.CrossEntropyLoss()

`run()` is a textbook training loop. Observed: the loop is emitted as an
`eval_loop` in the **eval** lane and `stages[eval].present` is true, on a class
that never evaluates anything.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


class Trainer:
    def __init__(self, ds):
        self.model = nn.Linear(16, 3)
        self.opt, self.crit = torch.optim.Adam(self.model.parameters()), nn.CrossEntropyLoss()
        self.loader = DataLoader(ds, batch_size=8, shuffle=True)

    def run(self):
        for xb, yb in self.loader:
            self.opt.zero_grad()
            loss = self.crit(self.model(xb), yb)
            loss.backward()
            self.opt.step()
        return self.model
