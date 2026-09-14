import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


SPEC = "nn.Linear(16, 3)"


def build(spec=SPEC):
    return eval(spec, {"nn": nn})


def patch(model, code="model.weight.data.zero_()"):
    exec(compile(code, "<patch>", "exec"), {"model": model})
    return model


def train(ds):
    model = patch(build())
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
