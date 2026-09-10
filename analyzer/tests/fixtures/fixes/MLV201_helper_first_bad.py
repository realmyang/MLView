# MLVIEW-EXPECT: MLV201 line=12 confidence>=0.6
"""H5-01: the training helper is defined ABOVE the caller that builds the
optimizer - the ordinary Python file layout (helpers first, `main()` last).

The optimizer reaches `train()` as a parameter, so it is bound before the
body runs at any line; the fix must therefore be offered here exactly as it is
in the twin whose definition order is reversed.

Never executed: MLView analyses this file statically.
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


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


def main():
    torch.manual_seed(0)
    dataset = TensorDataset(torch.randn(64, 8), torch.randint(0, 2, (64,)))
    net = nn.Sequential(nn.Linear(8, 2))
    optimizer = torch.optim.AdamW(net.parameters(), lr=1e-3)
    train(dataset, optimizer)
