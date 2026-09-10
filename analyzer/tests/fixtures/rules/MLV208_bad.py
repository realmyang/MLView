# MLVIEW-EXPECT: MLV208 line=25 confidence>=0.6
"""A GradScaler is created and then bypassed: the backward is unscaled, so every
half-precision gradient underflows to zero and whole layers stop learning."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(32, 4))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=1e-3)
    scaler = GradScaler("cpu")
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            with autocast("cpu"):
                loss = criterion(model(features), labels)
            loss.backward()
            scaler.step(optimizer)
            scaler.update()
    return model
