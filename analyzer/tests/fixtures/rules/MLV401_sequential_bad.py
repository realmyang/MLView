# MLVIEW-EXPECT: MLV401 line=21 confidence>=0.6
"""The bare-Sequential path ISSUE_RULES names explicitly: the model is not an
nn.Module subclass at all, it is a binding whose final nn.Sequential element is
nn.Softmax - and it is fed straight to CrossEntropyLoss."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    net = nn.Sequential(nn.Linear(10, 32), nn.ReLU(), nn.Linear(32, 3),
                        nn.Softmax(dim=1))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(net.parameters(), lr=1e-3)
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
    net.train()
    for features, labels in loader:
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(net(features), labels)
        loss.backward()
        optimizer.step()
