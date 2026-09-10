"""`getattr(torch.optim, cfg["optimizer"])` - the registry shape, resolved."""
from __future__ import annotations

import torch

CFG = {"optimizer": "AdamW", "lr": 0.0003}


def optimizer_for(model, cfg=CFG):
    factory = getattr(torch.optim, cfg["optimizer"])
    return factory(model.parameters(), lr=cfg["lr"])
