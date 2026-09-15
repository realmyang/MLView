
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .b import build_optimizer


def build_model():
    return nn.Linear(16, 3)


def train(ds):
    model = build_model()
    opt = build_optimizer(model)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
