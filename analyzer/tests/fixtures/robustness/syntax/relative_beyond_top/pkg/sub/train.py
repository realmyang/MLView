
from ...outside import helper  # beyond the top-level package
from ..shared import build_model
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(ds):
    model = build_model()
    helper()
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
