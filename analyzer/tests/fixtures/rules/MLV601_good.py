# MLVIEW-EXPECT-NONE: MLV601
"""The same pipeline, seeded at startup - including numpy and random."""
import random

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

SEED = 1337


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    model = nn.Sequential(nn.Linear(20, 2))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.05)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)
    for epoch in range(epochs):
        for features, labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
    return model


if __name__ == "__main__":
    set_seed()
    train(TensorDataset(torch.zeros(4, 20), torch.zeros(4, dtype=torch.long)))
