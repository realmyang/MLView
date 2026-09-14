"""ROB-11: an ignore directive that is *not* a comment still suppresses.

`Suppressor.index_module` scans raw line text with a regex and never looks at
tokens, so the string constant on the line above the loop header marks that
line as suppressed. The MLV201 finding on the loop header - the loop runs
`loss.backward()` and `opt.step()` with no `opt.zero_grad()`, so gradients
accumulate across batches - is then emitted with `suppressed: true`, and no
host ever shows it.

Nothing here is a comment. A suppression must come from a comment token, not
from text that happens to match inside a string.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    hint = "write # mlview: ignore[MLV201] on the loop header to silence this"
    for xb, yb in loader:
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model, hint
