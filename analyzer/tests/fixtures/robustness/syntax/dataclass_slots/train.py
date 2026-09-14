import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True, kw_only=True)
class TrainCfg:
    lr: float = 3e-4
    epochs: int = 5
    batch_size: int = 32
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class State:
    step: int = 0


def train(ds, cfg: TrainCfg = TrainCfg()):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=cfg.batch_size, shuffle=True)
    state = State()
    for _ in range(cfg.epochs):
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
            state.step += 1
    return model, state
