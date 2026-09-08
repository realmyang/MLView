# MLVIEW-EXPECT: MLV110 line=12 confidence>=0.6 severity=medium
"""The training loader consumes the dataset in file order, every epoch."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset, random_split


def build(dataset: TensorDataset):
    train_ds, val_ds = random_split(dataset, [45000, 5000],
                                    generator=torch.Generator().manual_seed(0))
    train_loader = DataLoader(train_ds, batch_size=64)
    val_loader = DataLoader(val_ds, batch_size=256, shuffle=False)
    return train_loader, val_loader


def train(dataset: TensorDataset, epochs: int = 2) -> None:
    torch.manual_seed(0)
    train_loader, _val_loader = build(dataset)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
