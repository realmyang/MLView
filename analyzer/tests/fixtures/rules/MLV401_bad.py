# MLVIEW-EXPECT: MLV401 line=31 confidence>=0.6
"""forward() ends in softmax while the loss is CrossEntropyLoss."""
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
        x = self.fc2(x)
        return F.softmax(x, dim=1)


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
