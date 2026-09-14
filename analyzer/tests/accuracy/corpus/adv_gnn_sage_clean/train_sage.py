"""Mini-batch GraphSAGE node classification with PyG NeighborLoader - correct.

Round 1's GNN pair was full-batch transductive GCN. This is the other half of
how graph code is actually written: neighbour sampling, one loader per split,
and a seed-node mask that decides which rows a loader yields.

Everything here is correct. The training loader shuffles, the evaluation
loaders do not, the sampler only ever seeds from its own split's mask, model
selection reads the validation mask and `test_mask` is touched exactly once at
the end, under eval mode and no_grad. Any high-severity finding is a false
positive.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.loader import NeighborLoader
from torch_geometric.nn import SAGEConv

SEED = 13
EPOCHS = 30
FANOUT = [15, 10]
BATCH_SIZE = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class SAGE(nn.Module):
    """Two SAGE layers returning raw class logits."""

    def __init__(self, in_channels: int, hidden: int, num_classes: int) -> None:
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden)
        self.conv2 = SAGEConv(hidden, num_classes)
        self.dropout = nn.Dropout(0.5)

    def forward(self, x, edge_index):
        h = self.conv1(x, edge_index)
        h = F.relu(h)
        h = self.dropout(h)
        return self.conv2(h, edge_index)


def build_loaders(data):
    """One loader per split; only the training loader shuffles its seed nodes."""
    train_loader = NeighborLoader(data, num_neighbors=FANOUT,
                                  batch_size=BATCH_SIZE,
                                  input_nodes=data.train_mask,
                                  shuffle=True, num_workers=4)
    val_loader = NeighborLoader(data, num_neighbors=FANOUT,
                                batch_size=BATCH_SIZE,
                                input_nodes=data.val_mask,
                                shuffle=False, num_workers=2)
    test_loader = NeighborLoader(data, num_neighbors=FANOUT,
                                 batch_size=BATCH_SIZE,
                                 input_nodes=data.test_mask,
                                 shuffle=False, num_workers=2)
    return train_loader, val_loader, test_loader


def train_epoch(model, loader, optimizer) -> float:
    model.train()
    running = 0.0
    batches = 0
    for batch in loader:
        batch = batch.to(DEVICE)
        optimizer.zero_grad(set_to_none=True)
        logits = model(batch.x, batch.edge_index)
        seeds = batch.batch_size
        loss = F.cross_entropy(logits[:seeds], batch.y[:seeds])
        loss.backward()
        optimizer.step()
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


@torch.no_grad()
def evaluate(model, loader) -> float:
    """Predicted classes, not logits, and no gradient anywhere."""
    model.eval()
    predicted = []
    truth = []
    for batch in loader:
        batch = batch.to(DEVICE)
        logits = model(batch.x, batch.edge_index)
        seeds = batch.batch_size
        predicted.append(logits[:seeds].argmax(dim=-1).cpu())
        truth.append(batch.y[:seeds].cpu())
    return float(accuracy_score(torch.cat(truth).numpy(),
                                torch.cat(predicted).numpy()))


def main() -> None:
    seed_everything(SEED)
    dataset = Planetoid(root="data/Planetoid", name="Cora")
    data = dataset[0]
    train_loader, val_loader, test_loader = build_loaders(data)

    model = SAGE(dataset.num_features, 128, dataset.num_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    best_val = 0.0
    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_loader, optimizer)
        val_accuracy = evaluate(model, val_loader)
        if val_accuracy > best_val:
            best_val = val_accuracy
            torch.save(model.state_dict(), "sage_best.pt")
        print("epoch %d loss %.4f val %.4f" % (epoch, loss, val_accuracy))

    state = torch.load("sage_best.pt", map_location=DEVICE, weights_only=True)
    model.load_state_dict(state)
    print("test accuracy %.4f" % evaluate(model, test_loader))


if __name__ == "__main__":
    main()
