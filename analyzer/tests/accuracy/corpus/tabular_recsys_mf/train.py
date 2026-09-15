"""Train the factorisation model, then measure hit-rate on the future window.

The loop is the ordinary four-line torch update in the ordinary order, the
evaluation pass switches the module to `eval()` and runs under `no_grad()`, and
the running loss is accumulated as a Python float.
"""
from __future__ import annotations

import random

import numpy as np
import torch
from torch.utils.data import DataLoader

from data import SEED, build_datasets
from model import MatrixFactorization, bpr_loss

N_USERS = 50000
N_ITEMS = 12000
EPOCHS = 8
BATCH_SIZE = 4096


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def build_loaders(csv_path: str):
    train_dataset, test_dataset = build_datasets(csv_path, N_ITEMS)
    generator = torch.Generator()
    generator.manual_seed(SEED)
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE,
                              shuffle=True, num_workers=4, generator=generator)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE,
                             shuffle=False, num_workers=4)
    return train_loader, test_loader


def train_one_epoch(model, loader, optimizer, device) -> float:
    model.train()
    running = 0.0
    for users, positives, negatives in loader:
        users = users.to(device)
        positives = positives.to(device)
        negatives = negatives.to(device)

        optimizer.zero_grad()
        positive_scores, negative_scores = model(users, positives, negatives)
        loss = bpr_loss(positive_scores, negative_scores)
        loss.backward()
        optimizer.step()

        running += loss.item()
    return running / max(1, len(loader))


def evaluate(model, loader, device) -> float:
    model.eval()
    hits = 0
    total = 0
    with torch.no_grad():
        for users, positives, negatives in loader:
            users = users.to(device)
            positives = positives.to(device)
            negatives = negatives.to(device)

            positive_scores, negative_scores = model(users, positives, negatives)
            hits += int((positive_scores > negative_scores).sum().item())
            total += users.shape[0]
    return hits / max(1, total)


def main(csv_path: str = "data/events.csv") -> dict:
    seed_everything()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    train_loader, test_loader = build_loaders(csv_path)
    model = MatrixFactorization(N_USERS, N_ITEMS).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-3, weight_decay=1e-6)

    history = []
    for _epoch in range(EPOCHS):
        history.append(train_one_epoch(model, train_loader, optimizer, device))

    torch.save(model.state_dict(), "artifacts/mf.pt")
    return {"loss_curve": history, "auc_proxy": evaluate(model, test_loader, device)}


if __name__ == "__main__":
    print(main())
