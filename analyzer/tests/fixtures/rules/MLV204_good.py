# MLVIEW-EXPECT-NONE: MLV204
"""The trap: the backward *is* lexically inside a torch.no_grad() block, but a
nested torch.enable_grad() re-enables autograd around it - the negating context
the scope pass has to track."""
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
                snapshot = model(features).detach()
                with torch.enable_grad():
                    loss = criterion(model(features), labels)
                    loss.backward()
            optimizer.step()
    return model
