# MLVIEW-EXPECT: MLV201 confidence>=0.6
"""H5, withheld: the batch loop's body starts on the `for` line itself.

The finding is real, and there is no place to put the edit: "insert above the
first body statement" is only a well-defined position when that statement
starts its own line. Here it does not, so an insertion would open a new line in
the middle of somebody's suite header. Prose, not an edit.
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
    loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in loader: loss = criterion(model(features), labels); loss.backward(); optimizer.step()
