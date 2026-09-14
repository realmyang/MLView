"""The recommender's training script, written the way it usually is first.

Planted defects:

* the evaluation pass never calls `model.eval()` and is not wrapped in
  `torch.no_grad()`, so dropout-free layers still build a graph and the whole
  holdout is materialised as autograd history;
* the running loss accumulates the *tensor* rather than `loss.item()`, which
  keeps every batch's graph alive for the whole epoch;
* the evaluation DataLoader shuffles;
* `num_workers=4` with the loaders built at module import time and no
  `__main__` guard;
* nothing is seeded anywhere;
* and, in `data.py`, the negative sampler is built from the full interaction
  table rather than from the training half.
"""
from __future__ import annotations

import torch
from torch.utils.data import DataLoader

from data import build_datasets
from model import MatrixFactorization, bpr_loss

N_USERS = 50000
N_ITEMS = 12000
EPOCHS = 8
BATCH_SIZE = 4096

TRAIN_DATASET, TEST_DATASET = build_datasets("data/events.csv", N_ITEMS)
train_loader = DataLoader(TRAIN_DATASET, batch_size=BATCH_SIZE, shuffle=True,
                          num_workers=4)
test_loader = DataLoader(TEST_DATASET, batch_size=BATCH_SIZE, shuffle=True,
                         num_workers=4)


def train_one_epoch(model, loader, optimizer):
    running = 0.0
    for users, positives, negatives in loader:
        optimizer.zero_grad()
        positive_scores, negative_scores = model(users, positives, negatives)
        loss = bpr_loss(positive_scores, negative_scores)
        loss.backward()
        optimizer.step()
        running = running + loss
    return running / max(1, len(loader))


def evaluate(model, loader):
    hits = 0
    total = 0
    for users, positives, negatives in loader:
        positive_scores, negative_scores = model(users, positives, negatives)
        hits += int((positive_scores > negative_scores).sum())
        total += users.shape[0]
    return hits / max(1, total)


def main():
    model = MatrixFactorization(N_USERS, N_ITEMS)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-3)

    history = []
    for _epoch in range(EPOCHS):
        history.append(train_one_epoch(model, train_loader, optimizer))

    return {"loss_curve": history, "auc_proxy": evaluate(model, test_loader)}


print(main())
