import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def build(kind: str):
    match kind:
        case "linear":
            return nn.Linear(16, 3)
        case "mlp" | "deep":
            return nn.Sequential(nn.Linear(16, 64), nn.ReLU(), nn.Linear(64, 3))
        case {"type": "conv", "width": int(width)}:
            return nn.Conv1d(1, width, 3)
        case [first, *rest]:
            return nn.Sequential(first, *rest)
        case _:
            raise ValueError(kind)


def train(ds, kind="mlp", epochs=3):
    model = build(kind)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for _ in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            out = model(xb)
            loss = crit(out, yb)
            loss.backward()
            opt.step()
    return model


def evaluate(model, loader):
    model.eval()
    total = 0
    with torch.no_grad():
        for xb, yb in loader:
            total += (model(xb).argmax(1) == yb).sum().item()
    return total
