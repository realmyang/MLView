"""Train the sentence encoder on paraphrase pairs.

Seven defects: the pair loss is fed raw similarity logits, the training loader
never shuffles, the split has no generator, the workers are spawned from module
scope, the loss is accumulated as a tensor, and the Spearman pass neither
switches to eval mode nor stops building the autograd graph.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from scipy.stats import spearmanr
from torch.utils.data import DataLoader, TensorDataset, random_split

from encoder import SentenceEncoder

EPOCHS = 5
BATCH_SIZE = 64
WORKERS = 4


def build_splits(path: str = "data/pairs.npz"):
    archive = np.load(path)
    dataset = TensorDataset(torch.from_numpy(archive["left_ids"]),
                            torch.from_numpy(archive["left_mask"]),
                            torch.from_numpy(archive["right_ids"]),
                            torch.from_numpy(archive["right_mask"]),
                            torch.from_numpy(archive["label"]))
    train_set, val_set = random_split(dataset, [0.9, 0.1])
    return train_set, val_set


train_split, val_split = build_splits()
train_loader = DataLoader(train_split, batch_size=BATCH_SIZE,
                          num_workers=WORKERS)
val_loader = DataLoader(val_split, batch_size=BATCH_SIZE, shuffle=False)


def train(model, device="cpu"):
    criterion = nn.BCELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
    model.to(device)
    model.train()
    running = 0.0
    for epoch in range(EPOCHS):
        for left_ids, left_mask, right_ids, right_mask, label in train_loader:
            optimizer.zero_grad()
            similarity = model(left_ids, left_mask, right_ids, right_mask)
            loss = criterion(similarity, label.float())
            loss.backward()
            optimizer.step()
            running += loss
        print("epoch", epoch, "loss", running)
    return model


def spearman(model):
    """Rank correlation on the validation pairs."""
    predicted = []
    gold = []
    for left_ids, left_mask, right_ids, right_mask, label in val_loader:
        similarity = model(left_ids, left_mask, right_ids, right_mask)
        predicted.extend(similarity.tolist())
        gold.extend(label.tolist())
    return spearmanr(predicted, gold).correlation


def main():
    model = SentenceEncoder()
    model = train(model)
    print("spearman", spearman(model))


main()
