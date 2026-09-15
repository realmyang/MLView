import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from typing import Protocol, TypedDict, overload, runtime_checkable


class Batch(TypedDict):
    x: torch.Tensor
    y: torch.Tensor


class Sample(TypedDict, total=False):
    weight: float


@runtime_checkable
class Fittable(Protocol):
    def fit(self, loader) -> "Fittable": ...


@overload
def build(kind: str) -> nn.Linear: ...
@overload
def build(kind: int) -> nn.Sequential: ...
def build(kind):
    if isinstance(kind, int):
        return nn.Sequential(nn.Linear(16, kind), nn.ReLU(), nn.Linear(kind, 3))
    return nn.Linear(16, 3)


def train(ds):
    model = build(64)
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
