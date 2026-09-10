# MLVIEW-EXPECT: MLV207 line=25 confidence>=0.6
"""StepLR is an epoch schedule, stepped once per batch, so the learning rate
decays to its floor inside the first epoch."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 5) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(16, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.1)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=0.5)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
            scheduler.step()
    return model
