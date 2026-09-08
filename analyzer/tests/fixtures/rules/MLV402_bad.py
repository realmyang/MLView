# MLVIEW-EXPECT: MLV402 line=31 confidence>=0.6 severity=high
"""forward() ends in nn.Sigmoid while the loss is BCEWithLogitsLoss, so the
sigmoid is applied twice and the gradient saturates."""
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class BinaryHead(nn.Module):
    def __init__(self, features: int = 10) -> None:
        super().__init__()
        self.fc1 = nn.Linear(features, 16)
        self.head = nn.Sequential(nn.Linear(16, 1), nn.Sigmoid())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(F.relu(self.fc1(x)))


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    model = BinaryHead()
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    model.train()
    for features, labels in loader:
        optimizer.zero_grad()
        probs = model(features)
        loss = criterion(probs, labels)
        loss.backward()
        optimizer.step()
