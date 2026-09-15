# MLVIEW-EXPECT-NONE: MLV205
"""REC-02: an accumulator that is one arithmetic step away from the tensor the
program back-propagates is holding its graph deliberately.

`style_loss += mse_loss(...)` inside the inner loop, `total_loss = content_loss
+ style_loss` after it, `total_loss.backward()` - taking `.item()` on
`style_loss` would detach half the objective and silently stop training that
term. The shape is `pytorch/examples/fast_neural_style/neural_style.py:91`.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 2) -> nn.Module:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    mse_loss = nn.MSELoss()
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    model.train()
    for _epoch in range(epochs):
        for features, targets in train_loader:
            optimizer.zero_grad()
            outputs = model(features)
            content_loss = mse_loss(outputs, targets)
            style_loss = 0.0
            for shift in range(3):
                style_loss += mse_loss(outputs.roll(shift, 0), targets)
            total_loss = content_loss + style_loss
            total_loss.backward()
            optimizer.step()
    return model
