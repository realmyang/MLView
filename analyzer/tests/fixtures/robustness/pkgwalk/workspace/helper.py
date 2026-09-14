"""ROB-21: a module beside the package, not inside it."""
import torch


def wrap(model):
    return torch.nn.Sequential(model)
