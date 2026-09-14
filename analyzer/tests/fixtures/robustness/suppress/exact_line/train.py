"""Positive control for ROB-11 and ROB-12: the spelling that does work.

A real comment, in the documented lower-case spelling, on the finding's own
line. MLView suppresses MLV201 here today and must keep doing so.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:  # mlview: ignore[MLV201]
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
