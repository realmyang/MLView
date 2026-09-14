
import torch


def build_optimizer(model):
    from .a import build_model  # circular, resolved lazily
    assert build_model is not None
    return torch.optim.Adam(model.parameters(), lr=1e-3)
