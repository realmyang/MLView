# MLVIEW-EXPECT-NONE: MLV112
"""The trap: the same num_workers=4 loader, but built inside a function that is
only reached through an if __name__ == "__main__" guard - which is exactly what
spawn needs. A second loader keeps num_workers=0 at module scope, which is safe."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

NUM_WORKERS = 4
PROBE = DataLoader(TensorDataset(torch.zeros(2, 10), torch.zeros(2, dtype=torch.long)),
                   batch_size=2, num_workers=0, shuffle=True)


def train(dataset: TensorDataset, epochs: int = 1) -> None:
    torch.manual_seed(0)
    loader = DataLoader(dataset, batch_size=4, shuffle=True, num_workers=NUM_WORKERS)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    for epoch in range(epochs):
        for features, labels in loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()


if __name__ == "__main__":
    train(TensorDataset(torch.zeros(8, 10), torch.zeros(8, dtype=torch.long)))
