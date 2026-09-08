# MLVIEW-EXPECT-NONE: MLV202
"""The trap: under AMP the step is `scaler.step(optimizer)`, not
`optimizer.step()`, and it only runs every ACCUM_STEPS batches - so the search
has to accept the GradScaler spelling and descend into the `if` body."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset

ACCUM_STEPS = 4


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    scaler = GradScaler("cuda")
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        for step, (features, labels) in enumerate(train_loader):
            with autocast("cuda"):
                loss = criterion(model(features), labels) / ACCUM_STEPS
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM_STEPS == 0:
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
    return model
