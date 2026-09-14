"""ROB-12: `# MLVIEW: ignore[MLV201]` is inert, and says nothing.

`IGNORE_RE` in `rules/suppress.py` is compiled with `re.IGNORECASE`, but the
fast-path guard one line above it is the case-sensitive `if "mlview" not in
text: continue`, so a capitalised directive never reaches the regex. The
configuration file accepts `disable = ["mlv201"]` in any case, and an ignore
comment naming an *unknown* code raises a `config_warning` - so this is the one
spelling that is neither honoured nor reported.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:  # MLVIEW: IGNORE[MLV201]
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
