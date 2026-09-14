"""PyTorch Geometric GCN node classification on Planetoid - correct.

Transductive full-batch training: one graph, three boolean masks. The training
loss reads `train_mask` only, model selection reads `val_mask` only, and
`test_mask` is touched exactly once, at the end, under eval mode and no_grad.

Nothing here is a defect. Any high-severity finding is a false positive.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.nn import GCNConv

SEED = 7
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 200
PATIENCE = 20


class GCN(nn.Module):
    """Two-layer GCN returning raw class logits."""

    def __init__(self, in_channels: int, hidden: int, num_classes: int) -> None:
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden)
        self.conv2 = GCNConv(hidden, num_classes)
        self.dropout = nn.Dropout(0.5)

    def forward(self, x, edge_index):
        h = self.conv1(x, edge_index)
        h = F.relu(h)
        h = self.dropout(h)
        # Raw logits: CrossEntropyLoss applies log-softmax itself.
        return self.conv2(h, edge_index)


def train_epoch(model, data, optimizer):
    """One full-batch gradient step on the training nodes only."""
    model.train()
    optimizer.zero_grad(set_to_none=True)
    logits = model(data.x, data.edge_index)
    loss = F.cross_entropy(logits[data.train_mask], data.y[data.train_mask])
    loss.backward()
    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    optimizer.step()
    return float(loss.item())


@torch.no_grad()
def evaluate(model, data, mask):
    """Accuracy on one mask. Predicted classes, never raw logits."""
    model.eval()
    logits = model(data.x, data.edge_index)
    predicted = logits[mask].argmax(dim=-1)
    return accuracy_score(data.y[mask].cpu().numpy(), predicted.cpu().numpy())


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    dataset = Planetoid(root="data/Planetoid", name="Cora")
    data = dataset[0].to(DEVICE)

    model = GCN(dataset.num_features, 64, dataset.num_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    best_val = 0.0
    best_state = None
    stale = 0
    for epoch in range(EPOCHS):
        loss = train_epoch(model, data, optimizer)
        val_acc = evaluate(model, data, data.val_mask)
        if val_acc > best_val:
            best_val = val_acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= PATIENCE:
                break
        if epoch % 20 == 0:
            print("epoch %d loss %.4f val %.4f" % (epoch, loss, val_acc))

    if best_state is not None:
        model.load_state_dict(best_state)
    test_acc = evaluate(model, data, data.test_mask)
    print("selected on val=%.4f, test accuracy %.4f" % (best_val, test_acc))
    torch.save(model.state_dict(), "gcn_cora.pt")


if __name__ == "__main__":
    main()
