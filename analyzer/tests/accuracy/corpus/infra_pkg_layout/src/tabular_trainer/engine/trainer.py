"""The training half of the engine. Correct on purpose."""
from __future__ import annotations

import torch
import torch.nn as nn

from ..config import TrainConfig
from ..utils.logging import get_logger
from ..utils.timing import Stopwatch
from .evaluator import evaluate

log = get_logger(__name__)


def train(model: nn.Module, train_loader, test_loader, cfg: TrainConfig):
    device = torch.device(cfg.device)
    model = model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr,
                                  weight_decay=cfg.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=cfg.epochs)

    history = []
    for epoch in range(cfg.epochs):
        with Stopwatch("epoch %d" % epoch) as watch:
            loss = _one_epoch(model, train_loader, optimizer, criterion, device)
            accuracy = evaluate(model, test_loader, device)
        scheduler.step()
        history.append({"epoch": epoch, "loss": loss, "accuracy": accuracy})
        log.info("%s loss=%.4f acc=%.4f", watch, loss, accuracy)
    return history


def _one_epoch(model, loader, optimizer, criterion, device) -> float:
    model.train()
    running = 0.0
    for features, labels in loader:
        features = features.to(device)
        labels = labels.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)
