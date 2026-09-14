"""The evaluation half of the engine.

Correct on purpose: `model.eval()` before the loop, `torch.no_grad()` around
it, training mode restored on the way out, batches moved to the model's
device, and the accuracy computed from `argmax` rather than from raw logits.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score


def evaluate(model: nn.Module, loader, device) -> float:
    model.eval()
    predictions = []
    references = []
    with torch.no_grad():
        for features, labels in loader:
            features = features.to(device)
            labels = labels.to(device)
            logits = model(features)
            predictions.append(logits.argmax(dim=1).cpu())
            references.append(labels.cpu())
    model.train()
    predicted = torch.cat(predictions).numpy()
    actual = torch.cat(references).numpy()
    return float(accuracy_score(actual, predicted))


def report(model: nn.Module, loader, device) -> dict:
    model.eval()
    predictions = []
    references = []
    with torch.no_grad():
        for features, labels in loader:
            logits = model(features.to(device))
            predictions.append(logits.argmax(dim=1).cpu())
            references.append(labels.cpu())
    model.train()
    predicted = torch.cat(predictions).numpy()
    actual = torch.cat(references).numpy()
    return {"accuracy": float(accuracy_score(actual, predicted)),
            "f1": float(f1_score(actual, predicted, average="macro"))}
