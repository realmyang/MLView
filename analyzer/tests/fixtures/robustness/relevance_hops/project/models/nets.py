"""Hop 0 - the only module in this package that names the framework."""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def make_model():
    return nn.Linear(16, 3)


def make_optimizer(model):
    return torch.optim.Adam(model.parameters(), lr=1e-3)


def make_criterion():
    return nn.CrossEntropyLoss()


def make_loader(dataset):
    return DataLoader(dataset, batch_size=8, shuffle=True)
