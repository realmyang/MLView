# MLVIEW-EXPECT-NONE: MLV401
"""forward() returns raw logits; softmax only where probabilities are reported."""
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


class SmallNet(nn.Module):
    def __init__(self, features: int = 10, classes: int = 3) -> None:
        super().__init__()
        self.fc1 = nn.Linear(features, 32)
        self.fc2 = nn.Linear(32, classes)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def probabilities(model: nn.Module, batch) -> torch.Tensor:
    with torch.no_grad():
        return F.softmax(model(batch), dim=1)


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    model = SmallNet()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    for features, labels in loader:
        optimizer.zero_grad()
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
