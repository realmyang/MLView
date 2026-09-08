# MLVIEW-EXPECT: MLV201 line=21 confidence>=0.6
"""Batch loop with backward() and step() but never zero_grad().

Never executed: MLView analyses this file statically.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 5) -> None:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            outputs = model(features)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
