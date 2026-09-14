# MLVIEW-EXPECT: MLV205 line=29
"""vision-06. The canonical placement: the accumulator is reset once per epoch
and accumulated once per batch.

`_defined_outside` skipped a candidate initializer when `_within(loop,
other.loop)` was true, with the comment "created inside the same loop: reset
each pass" - but `_within(a, b)` asks whether `a` is inside `b`, so the test
read "is the accumulating loop nested inside the initializer's loop", which is
exactly true for this shape. The rule therefore only ever worked when the
accumulator was initialised outside EVERY loop, and missed the placement every
PyTorch tutorial writes.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 3) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for epoch in range(epochs):
        running = 0.0
        batches = 0
        for features, labels in train_loader:
            optimizer.zero_grad()
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
            running += loss
            batches += 1
        print("epoch", epoch, "loss", running / max(batches, 1))
    return model
