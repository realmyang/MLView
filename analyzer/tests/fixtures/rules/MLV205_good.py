# MLVIEW-EXPECT-NONE: MLV205
"""The trap: `total_loss = total_loss + loss` is deliberate - the accumulator
itself is back-propagated once per epoch - while the reporting accumulator uses
.item() and the per-batch list is detached."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    running_loss = 0.0
    history = []
    for epoch in range(epochs):
        total_loss = 0.0
        for features, labels in train_loader:
            loss = criterion(model(features), labels)
            total_loss = total_loss + loss
            running_loss += loss.item()
            history.append(loss.detach())
        optimizer.zero_grad()
        total_loss.backward()
        optimizer.step()
    return model
