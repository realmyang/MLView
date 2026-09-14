"""One framework file, so the workspace analyzes to something."""

from __future__ import annotations

import torch
import torch.nn as nn

MODEL = nn.Linear(3, 2)
OPTIMIZER = torch.optim.SGD(MODEL.parameters(), lr=0.1)
