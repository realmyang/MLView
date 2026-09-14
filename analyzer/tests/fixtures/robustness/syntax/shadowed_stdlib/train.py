
import random
import torch

from torch import nn


def train(ds):
    random.seed(7)
    model = nn.Linear(16, 3)
    return torch.device("cpu"), model
