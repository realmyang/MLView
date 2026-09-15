import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


BUILDERS = {
    "linear": lambda: nn.Linear(16, 3),
    "mlp": lambda w=32: nn.Sequential(nn.Linear(16, w), nn.ReLU(), nn.Linear(w, 3)),
}
LOSSES = {"ce": lambda: nn.CrossEntropyLoss(), "mse": nn.MSELoss}


def train(ds, kind="mlp", loss="ce"):
    model = BUILDERS[kind]()
    crit = LOSSES[loss]()
    opt = (lambda p: torch.optim.Adam(p, lr=1e-3))(model.parameters())
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
