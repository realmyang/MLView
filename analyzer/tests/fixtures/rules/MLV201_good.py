# MLVIEW-EXPECT-NONE: MLV201
"""Gradient accumulation: zero_grad() lives under `if step % 4 == 0`.

The nearest false-positive trap for MLV201 - the call is there, just guarded.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

ACCUM_STEPS = 4


def train(dataset: TensorDataset, epochs: int = 5) -> None:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for step, (features, labels) in enumerate(train_loader):
            if step % ACCUM_STEPS == 0:
                optimizer.zero_grad(set_to_none=True)
            outputs = model(features)
            loss = criterion(outputs, labels) / ACCUM_STEPS
            loss.backward()
            if (step + 1) % ACCUM_STEPS == 0:
                optimizer.step()
