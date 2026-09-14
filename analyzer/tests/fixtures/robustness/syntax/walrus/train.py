import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def train(ds, epochs=2):
    model = nn.Linear(16, 3)
    opt = torch.optim.SGD(model.parameters(), lr=0.1)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=4)
    best = float("inf")
    for _ in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            if (loss := crit(model(xb), yb)) < best:
                best = loss.item()
            loss.backward()
            opt.step()
    return model, best
