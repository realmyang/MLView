# MLVIEW-EXPECT: MLV601 line=27 confidence>=0.6
"""A complete little pipeline with no seed anywhere."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def build_loader(dataset: TensorDataset) -> DataLoader:
    return DataLoader(dataset, batch_size=64, shuffle=True)


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    model = nn.Sequential(nn.Linear(20, 2))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.05)
    loader = build_loader(dataset)
    for epoch in range(epochs):
        for features, labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
    return model


if __name__ == "__main__":
    train(TensorDataset(torch.zeros(4, 20), torch.zeros(4, dtype=torch.long)))
