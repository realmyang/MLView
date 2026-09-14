"""PyTorch Geometric GCN node classification - the defective twin.

Same two-layer GCN on the same transductive split, written the way it goes
wrong: the training loss reads the test mask, the logits are soft-maxed before
a cross-entropy that soft-maxes them again, the evaluation helper never leaves
train mode, accuracy is computed on raw logits, and nothing is seeded.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.nn import GCNConv

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 200


class GCN(nn.Module):
    def __init__(self, in_channels: int, hidden: int, num_classes: int) -> None:
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden)
        self.conv2 = GCNConv(hidden, num_classes)
        self.dropout = nn.Dropout(0.5)

    def forward(self, x, edge_index):
        h = self.conv1(x, edge_index)
        h = F.relu(h)
        h = self.dropout(h)
        return self.conv2(h, edge_index)


def train_epoch(model, data, optimizer):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    logits = model(data.x, data.edge_index)
    # DEFECT: softmax is applied before cross_entropy, which applies
    # log-softmax again, so the gradient is flattened towards zero.
    probabilities = F.softmax(logits, dim=-1)
    # DEFECT: the loss reads test_mask, so every reported test number is a
    # training number and the held-out split does not exist.
    loss = F.cross_entropy(probabilities[data.test_mask], data.y[data.test_mask])
    loss.backward()
    optimizer.step()
    return float(loss.item())


def evaluate(model, data, mask):
    """DEFECT: no model.eval(), so the 0.5 dropout stays active during scoring,
    and DEFECT: no torch.no_grad(), so a full autograd graph is built for a
    measurement that is never differentiated."""
    logits = model(data.x, data.edge_index)
    # DEFECT: accuracy is computed on raw logits rather than on argmax classes.
    return accuracy_score(data.y[mask].cpu().numpy(),
                          logits[mask].detach().cpu().numpy())


def main() -> None:
    # DEFECT: nothing is seeded, so the dropout mask, the parameter init and
    # therefore the reported accuracy move between runs.
    dataset = Planetoid(root="data/Planetoid", name="Cora")
    data = dataset[0].to(DEVICE)

    model = GCN(dataset.num_features, 64, dataset.num_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    best_test = 0.0
    for epoch in range(EPOCHS):
        loss = train_epoch(model, data, optimizer)
        # DEFECT: the checkpoint is selected on the test mask, so the reported
        # figure is the maximum over 200 draws of the test set.
        test_acc = evaluate(model, data, data.test_mask)
        if test_acc > best_test:
            best_test = test_acc
            torch.save(model, "gcn_cora_best.pt")
        if epoch % 20 == 0:
            print("epoch %d loss %.4f test %.4f" % (epoch, loss, test_acc))

    print("best test accuracy %.4f" % best_test)


if __name__ == "__main__":
    main()
