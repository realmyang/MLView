# MLVIEW-EXPECT-NONE: MLV205
"""PUB-08 / INFRA-01. The trap: a Python float accumulated under no_grad.

`avg_psnr += psnr` where `psnr = 10 * log10(1 / mse.item())` one line earlier:
`.item()` has already detached the value and `math.log10` cannot return a
tensor, so the accumulator holds a float and `no_grad` recorded no graph for it
to keep alive. Both halves of the emitted sentence ("accumulates the tensor
psnr ... keeps its autograd graph alive") were false, and the rule's own advice
was already followed one line above. This is
`pytorch/examples/super_resolution/main.py:72`.
"""
from math import log10

import torch
import torch.nn as nn


def evaluate(model: nn.Module, loader, criterion: nn.Module) -> float:
    torch.manual_seed(0)
    model.eval()
    avg_psnr = 0.0
    with torch.no_grad():
        for inputs, target in loader:
            mse = criterion(model(inputs), target)
            psnr = 10 * log10(1 / mse.item())
            avg_psnr += psnr
    return avg_psnr / max(len(loader), 1)


def validate(model: nn.Module, loader, criterion: nn.Module) -> float:
    model.eval()
    total = 0.0
    with torch.no_grad():
        for inputs, target in loader:
            total += criterion(model(inputs), target)
    return float(total) / max(len(loader), 1)
