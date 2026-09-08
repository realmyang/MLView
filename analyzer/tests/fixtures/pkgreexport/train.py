"""The entrypoint imports both packages by their re-exported names."""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from src.data import WindowDataset
from src.models import Net, build_optimizer


def main() -> None:
    torch.manual_seed(0)
    series = torch.randn(1000, 16)
    train_ds = WindowDataset(series, width=16)
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True)
    model = Net(width=16)
    criterion = nn.MSELoss()
    optimizer = build_optimizer(model, lr=1e-3)
    model.train()
    for windows, target in train_loader:
        optimizer.zero_grad()
        loss = criterion(model(windows), target)
        loss.backward()
        optimizer.step()


if __name__ == "__main__":
    main()
