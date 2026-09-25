"""Model construction is selected by configuration, not a fixed call name."""
from torch import nn


def small():
    return nn.Sequential(nn.Linear(10, 16), nn.ReLU(), nn.Linear(16, 3))


def wide():
    return nn.Sequential(nn.Linear(10, 64), nn.ReLU(), nn.Linear(64, 3))


BUILDERS = {"small": small, "wide": wide}


def build(name):
    return BUILDERS[name]()
