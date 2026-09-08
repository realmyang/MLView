# MLVIEW-EXPECT-NONE: MLV201, MLV202, MLV203
"""The trap: the optimizer never appears in the training function. It comes
back from a factory that returns a different class per branch, through a second
helper that hands back a `(optimizer, scheduler)` tuple. Without one level of
return-type inference `opt` is untyped, `opt.step()` resolves to nothing and
both absence rules fire on perfectly correct code."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader, TensorDataset


def build_optimizer(model: nn.Module, name: str):
    if name == "adam":
        return optim.Adam(model.parameters(), lr=1e-3)
    return optim.SGD(model.parameters(), lr=0.01)


def build_schedule(model: nn.Module, name: str, epochs: int):
    optimizer = build_optimizer(model, name)
    return optimizer, CosineAnnealingLR(optimizer, T_max=epochs)


def train(dataset: TensorDataset, name: str = "adam", epochs: int = 2) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    opt, sched = build_schedule(model, name, epochs)
    loader = DataLoader(dataset, batch_size=32, shuffle=True)
    model.train()
    for features, labels in loader:
        opt.zero_grad(set_to_none=True)
        loss = criterion(model(features), labels)
        loss.backward()
        opt.step()
    sched.step()
    return model
