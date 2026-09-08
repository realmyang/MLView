# MLVIEW-EXPECT: MLV202 line=18 confidence>=0.6 severity=high ghost=true
"""The optimizer is built and zeroed, but step() is never called."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
    return model
