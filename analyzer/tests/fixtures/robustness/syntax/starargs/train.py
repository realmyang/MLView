import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def make_optimizer(params, *args, **kwargs):
    return torch.optim.Adam(params, *args, **kwargs)


def forward_all(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


def train(ds, *loaders, lr=1e-3, **extra):
    model = nn.Linear(16, 3)
    opt = forward_all(make_optimizer, model.parameters(), lr=lr, **extra)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, *loaders, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
