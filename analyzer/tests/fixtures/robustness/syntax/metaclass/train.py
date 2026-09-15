import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


REGISTRY = {}


class Registered(type):
    def __new__(mcls, name, bases, ns, **kw):
        cls = super().__new__(mcls, name, bases, ns)
        REGISTRY[name.lower()] = cls
        return cls

    def __call__(cls, *args, **kwargs):
        return super().__call__(*args, **kwargs)


class Base(nn.Module, metaclass=Registered):
    pass


class SmallNet(Base):
    def __init__(self, width=32):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(16, width), nn.ReLU(), nn.Linear(width, 3))

    def forward(self, x):
        return self.net(x)


def train(ds):
    model = REGISTRY["smallnet"]()
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
