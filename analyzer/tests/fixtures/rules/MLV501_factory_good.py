# MLVIEW-EXPECT-NONE: MLV501, MLV301, MLV302
"""The trap: the network comes back from a factory, so `build_model(width).to(
device)` is the only move of an nn.Module in the file - and the device is the
literal 'cpu' anyway. Both halves of MLV501 have to resolve that before
accusing anyone, and the eval loop's own batch move sits in another function."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class Net(nn.Module):
    def __init__(self, width: int) -> None:
        super().__init__()
        self.drop = nn.Dropout(0.1)
        self.fc = nn.Linear(10, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(self.drop(x))


def build_model(width: int) -> Net:
    return Net(width)


def evaluate(model: Net, loader: DataLoader, device: torch.device) -> int:
    model.eval()
    with torch.no_grad():
        return sum((model(f.to(device)).argmax(1) == y.to(device)).sum().item()
                   for f, y in loader)


def train(dataset: TensorDataset) -> int:
    torch.manual_seed(0)
    device = torch.device("cpu")
    model = build_model(32).to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()
    loader = DataLoader(dataset, batch_size=32, shuffle=True)
    model.train()
    for features, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        features, labels = features.to(device), labels.to(device)
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
    return evaluate(model, loader, device)
