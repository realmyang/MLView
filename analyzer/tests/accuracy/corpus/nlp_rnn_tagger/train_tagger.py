"""Train the BiLSTM tagger on a padded tensor corpus.

Five defects: the optimizer is stepped before the backward pass, the split has
no generator, the epoch loss is accumulated as a tensor, the evaluation pass
runs with dropout still active and with the autograd graph switched on, and
nothing is seeded.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset, random_split

from tagger import PAD_INDEX, BiLSTMTagger, sequence_loss

EPOCHS = 8
BATCH_SIZE = 32
LEARNING_RATE = 1e-3


def load_corpus(path: str = "data/pos.npz"):
    archive = np.load(path)
    dataset = TensorDataset(torch.from_numpy(archive["tokens"]),
                            torch.from_numpy(archive["lengths"]),
                            torch.from_numpy(archive["tags"]))
    train_set, val_set = random_split(dataset, [0.85, 0.15])
    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False)
    return train_loader, val_loader


def train_one_epoch(model, optimizer, train_loader):
    running = 0.0
    for tokens, lengths, tags in train_loader:
        optimizer.zero_grad()
        logits = model(tokens, lengths)
        loss = sequence_loss(logits, tags)
        optimizer.step()
        loss.backward()
        running += loss
    return running


def evaluate(model, val_loader):
    """Tag accuracy over the validation split, padding positions removed."""
    hits = 0
    total = 0
    for tokens, lengths, tags in val_loader:
        logits = model(tokens, lengths)
        predicted = logits.argmax(dim=-1)
        keep = tags != PAD_INDEX
        hits += int((predicted[keep] == tags[keep]).sum())
        total += int(keep.sum())
    return hits / max(total, 1)


def main():
    train_loader, val_loader = load_corpus()
    model = BiLSTMTagger()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    for epoch in range(EPOCHS):
        loss = train_one_epoch(model, optimizer, train_loader)
        print("epoch", epoch, "loss", loss, "val", evaluate(model, val_loader))
    torch.save(model.state_dict(), "runs/tagger.pt")


main()
