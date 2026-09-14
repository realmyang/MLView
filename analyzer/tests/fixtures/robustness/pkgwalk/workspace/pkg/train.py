"""ROB-21. Analyze `pkg/`; MLView reads `../` and says so in the document.

`import helper` is what arms `single_file_diagnostic`: the rule is "the
analyzed set is a strict subset of what is discoverable under the owning
package root, and one analyzed module imports one of the modules left out".
The owning package root is computed by climbing while the directory holds an
`__init__.py`, which walks *out of the workspace the caller named*.

Observed, analysing this directory::

    workspace.root        .../pkgwalk/workspace/pkg
    single_file_analysis  "Only pkg/train.py was analyzed: 3 sibling module(s)
                           in the same package were not (helper.py,
                           pkg/__init__.py, sibling_project/other.py), and
                           pkg/train.py imports 1 of them."

`helper.py` and `sibling_project/other.py` are not in this package and are not
under `workspace.root`; the sentence says they are. The walk that produced
them is unbounded -- `discover(..., max_files=1000)` truncates the *result*,
never the `os.walk`, so the cost is the size of the whole parent tree. Measured
on a 200-module workspace sitting in a busy directory: **0.33 s with the root
`__init__.py` removed, 5.37 s with it present**, 94% of the run spent walking a
directory the user never named, for a diagnostic that was not even emitted.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

import helper


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return helper.wrap(model)
