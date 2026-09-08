# MLVIEW-EXPECT-NONE: MLV501
"""The trap: the batch is not moved in the loop body either - the Dataset's
__getitem__ already returns device tensors, which the rule has to resolve
before it accuses anyone."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class OnDeviceDataset(Dataset):
    def __init__(self, features: torch.Tensor, labels: torch.Tensor) -> None:
        self.features = features
        self.labels = labels

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, index: int):
        return self.features[index].to(DEVICE), self.labels[index].to(DEVICE)


def train(dataset: OnDeviceDataset, epochs: int = 2) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    model.to(DEVICE)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
    return model
