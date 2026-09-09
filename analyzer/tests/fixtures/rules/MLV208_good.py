# MLVIEW-EXPECT-NONE: MLV208
"""The trap: the whole AMP protocol written correctly under a gradient
accumulation guard, so scale, unscale_, clip, step and update are spread over
two blocks of the same loop. This is the shape analyzer/tests/clean/
amp_accumulation.py exercises, and the ordering checks must not read across it."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset

ACCUM = 4


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(32, 4))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=1e-3)
    scaler = GradScaler("cpu")
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        for step, (features, labels) in enumerate(train_loader):
            with autocast("cpu"):
                loss = criterion(model(features), labels) / ACCUM
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM == 0:
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
    return model
