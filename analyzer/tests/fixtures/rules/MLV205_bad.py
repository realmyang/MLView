# MLVIEW-EXPECT: MLV205 line=24 confidence>=0.6 severity=medium
"""running_loss += loss keeps every batch's autograd graph alive for the epoch."""
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
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
            running_loss += loss
    return model
