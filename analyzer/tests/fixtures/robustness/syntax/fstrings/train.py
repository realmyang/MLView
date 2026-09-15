import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def train(ds, epochs=2):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    names = {"loss": "train/loss"}
    for epoch in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
            print(f"{names["loss"]}={loss.item():.4f} epoch={epoch!r:>3}")
            print(f"{f'{loss.item():.2f}'} nested {'{'} brace")
            print(f"""multi {names['loss']}
            line {loss.item()}""")
    return model
