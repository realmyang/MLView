import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

__all__ = ["build_model", "CRIT", "make_loader"]


def build_model(width=32):
    return nn.Sequential(nn.Linear(16, width), nn.ReLU(), nn.Linear(width, 3))


CRIT = nn.CrossEntropyLoss


def make_loader(ds, bs=8):
    return DataLoader(ds, batch_size=bs, shuffle=True)
