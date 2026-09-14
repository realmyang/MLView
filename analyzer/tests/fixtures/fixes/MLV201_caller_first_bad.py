# MLVIEW-EXPECT: MLV201 line=23 confidence>=0.6
"""H5-01: the same program as `MLV201_helper_first_bad.py`, with `main()`
moved ABOVE `train()`.

Nothing else differs. Before H5-01 the fix appeared only in this order,
because `_defined_after` compared the optimizer's producer line against the
insertion line without asking whether the two were in the same scope.

Never executed: MLView analyses this file statically.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def main():
    torch.manual_seed(0)
    dataset = TensorDataset(torch.randn(64, 8), torch.randint(0, 2, (64,)))
    net = nn.Sequential(nn.Linear(8, 2))
    optimizer = torch.optim.AdamW(net.parameters(), lr=1e-3)
    train(dataset, optimizer)


def train(dataset, optimizer):
    model = nn.Sequential(nn.Linear(8, 2))
    criterion = nn.CrossEntropyLoss()
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)
    model.train()
    for epoch in range(3):
        for features, labels in train_loader:
            outputs = model(features)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
