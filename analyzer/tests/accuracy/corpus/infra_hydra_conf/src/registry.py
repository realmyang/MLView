"""Name -> constructor registries, plus `getattr` dispatch into torch.optim.

The whole repo is configured by name: `cfg.model.name` picks a class out of
`MODELS`, `cfg.optimizer.name` is looked up on `torch.optim` with `getattr`.
Nothing here is a defect; it is the indirection a research repo always has.
"""
from __future__ import annotations

from typing import Callable, Dict

import torch
import torch.nn as nn

from .models import ResNetTiny, WideMLP

MODELS: Dict[str, Callable[..., nn.Module]] = {
    "resnet_tiny": ResNetTiny,
    "wide_mlp": WideMLP,
}

LOSSES: Dict[str, Callable[..., nn.Module]] = {
    "cross_entropy": nn.CrossEntropyLoss,
    "label_smoothing": lambda: nn.CrossEntropyLoss(label_smoothing=0.1),
}


def build_model(cfg) -> nn.Module:
    factory = MODELS[cfg.model.name]
    return factory(width=cfg.model.width, depth=cfg.model.depth,
                   dropout=cfg.model.dropout, classes=cfg.model.classes)


def build_optimizer(cfg, parameters):
    factory = getattr(torch.optim, cfg.optimizer.name)
    if cfg.optimizer.name == "SGD":
        return factory(parameters, lr=cfg.optimizer.lr,
                       momentum=cfg.optimizer.momentum,
                       weight_decay=cfg.optimizer.weight_decay)
    return factory(parameters, lr=cfg.optimizer.lr,
                   weight_decay=cfg.optimizer.weight_decay)


def build_loss(name: str = "cross_entropy") -> nn.Module:
    return LOSSES[name]()
