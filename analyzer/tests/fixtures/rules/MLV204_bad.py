# MLVIEW-EXPECT: MLV204 line=22 confidence>=0.6 severity=high
"""backward() inside torch.no_grad(): there is no graph to walk."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 2) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            with torch.no_grad():
                loss = criterion(model(features), labels)
                loss.backward()
            optimizer.step()
    return model
