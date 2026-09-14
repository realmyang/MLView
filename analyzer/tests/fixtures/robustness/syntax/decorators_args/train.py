import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

import functools


def retry(times=3, *, backoff=0.1):
    def deco(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            for _ in range(times):
                try:
                    return fn(*args, **kwargs)
                except RuntimeError:
                    pass
            raise RuntimeError("gave up")
        return inner
    return deco


@retry(times=2, backoff=0.5)
@torch.no_grad()
def evaluate(model, loader):
    model.eval()
    return sum((model(xb).argmax(1) == yb).float().mean().item() for xb, yb in loader)


@retry()
def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
