import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from typing import Iterable

type Batch = tuple[torch.Tensor, torch.Tensor]


class Runner[T]:
    def __init__(self, model: T) -> None:
        self.model = model
        self.opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        self.crit = nn.CrossEntropyLoss()

    def fit[B: Batch](self, loader: Iterable[B]):
        for xb, yb in loader:
            self.opt.zero_grad()
            loss = self.crit(self.model(xb), yb)
            loss.backward()
            self.opt.step()
        return self.model


def make[M: nn.Module](cls: type[M]) -> M:
    return cls(16, 3)


def main(ds):
    runner = Runner(make(nn.Linear))
    return runner.fit(DataLoader(ds, batch_size=8, shuffle=True))
