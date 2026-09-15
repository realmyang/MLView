"""The driver half of the GRAPH-R3 fixture: objects reached through things.

Five ways a real training script hands an object to the line that uses it, and
every one of them drew nothing before this fixture existed:

* `self.<attr>` set in `__init__` and applied in a **sibling method**
  (`Runner.step`);
* a **dict** built in one place and read in another (`ctx["scaler"]`, the
  GradScaler case the roadmap entry names);
* a **dataclass** field (`bundle.model`);
* a **tuple** unpacked from a name (`opt_a, opt_b = optimizers`);
* a **rebinding wrapper** that hands back what it was given
  (`accelerator.prepare`).

Line numbers are asserted in `analyzer/tests/core/test_workspace_ops.py`, so
inserting a line here means updating that file - which is the point: the whole
claim is *which line the card lands on*.
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch.amp import GradScaler

from lib import (FocalLoss, TinyNet, build_loaders, build_model,
                 build_optimizer, build_scheduler)


@dataclass
class Bundle:
    model: TinyNet
    optimizer: torch.optim.Optimizer


class Runner:
    """`self.<attr>` built in `__init__`, applied in a sibling method."""

    def __init__(self, path):
        self.model = build_model()
        self.criterion = FocalLoss()
        self.train_loader, self.val_loader = build_loaders(path)

    def step(self, batch):
        features, labels = batch
        logits = self.model(features)
        return self.criterion(logits, labels)

    def run(self):
        for batch in self.train_loader:
            loss = self.step(batch)
            loss.backward()


def main(path="shards"):
    model = build_model()
    optimizer = build_optimizer(model)
    scheduler = build_scheduler(optimizer)
    train_loader, val_loader = build_loaders(path)
    ctx = {"scaler": GradScaler("cuda"), "model": model}
    scaler = ctx["scaler"]
    bundle = Bundle(model=model, optimizer=optimizer)
    criterion = FocalLoss()
    for features, labels in train_loader:
        optimizer.zero_grad()
        logits = bundle.model(features)
        loss = criterion(logits, labels)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
    scheduler.step()
    return model, scaler, val_loader


def paired(path="shards"):
    optimizers = (build_optimizer(build_model()), build_optimizer(build_model()))
    opt_a, opt_b = optimizers
    opt_a.step()
    opt_b.step()
    return opt_a, opt_b


def accelerated(path="shards"):
    from accelerate import Accelerator

    accelerator = Accelerator()
    net = TinyNet(16)
    optimizer = build_optimizer(net)
    train_loader, _val = build_loaders(path)
    net, optimizer, train_loader = accelerator.prepare(net, optimizer, train_loader)
    criterion = FocalLoss()
    for features, labels in train_loader:
        optimizer.zero_grad()
        loss = criterion(net(features), labels)
        accelerator.backward(loss)
        optimizer.step()
    return net
