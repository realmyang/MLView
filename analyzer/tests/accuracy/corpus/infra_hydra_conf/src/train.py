"""The Hydra entrypoint.

    python -m src.train optimizer=sgd model.width=128

Planted defects, both in `evaluate()`:

* the model is never switched to `eval()`, so ResNetTiny's Dropout and
  BatchNorm run in training mode over the validation set (MLV301);
* the loop is not wrapped in `torch.no_grad()`, so an autograd graph is built
  for every validation batch and thrown away (MLV302).

Everything else is correct: the seed is set from the config, the batch loop
zeroes, backwards, clips and steps in that order, and batches are moved to the
configured device on both paths.
"""
from __future__ import annotations

import logging
import os

import hydra
import torch
import torch.nn as nn
from omegaconf import DictConfig, OmegaConf

from .data import build_loaders
from .registry import build_loss, build_model, build_optimizer

log = logging.getLogger(__name__)


def train_one_epoch(model, loader, optimizer, criterion, device) -> float:
    model.train()
    running = 0.0
    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(images), targets)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


def evaluate(model, loader, device) -> float:
    hits = 0
    seen = 0
    for images, targets in loader:
        images = images.to(device)
        targets = targets.to(device)
        logits = model(images)
        hits += (logits.argmax(dim=1) == targets).sum().item()
        seen += targets.numel()
    return hits / max(seen, 1)


@hydra.main(version_base=None, config_path="../conf", config_name="config")
def main(cfg: DictConfig) -> None:
    log.info(OmegaConf.to_yaml(cfg))
    torch.manual_seed(cfg.seed)

    device = torch.device(cfg.device if torch.cuda.is_available() else "cpu")
    model = build_model(cfg).to(device)
    criterion = build_loss()
    optimizer = build_optimizer(cfg, model.parameters())
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=cfg.epochs)
    train_loader, val_loader = build_loaders(cfg)

    best = 0.0
    for epoch in range(cfg.epochs):
        loss = train_one_epoch(model, train_loader, optimizer, criterion,
                               device)
        accuracy = evaluate(model, val_loader, device)
        scheduler.step()
        log.info("epoch %d loss %.4f acc %.4f", epoch, loss, accuracy)
        if accuracy > best:
            best = accuracy
            os.makedirs("checkpoints", exist_ok=True)
            torch.save(model.state_dict(), "checkpoints/best.pt")


if __name__ == "__main__":
    main()
