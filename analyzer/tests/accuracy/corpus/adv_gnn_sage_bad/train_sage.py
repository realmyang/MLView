"""Mini-batch GraphSAGE - the defective twin of adv_gnn_sage_clean.

Nine defects are planted across the two files. The two that matter most to a
graph reviewer are graph-specific and have no rule in the catalog: the sampler
that seeds from every node instead of the training mask, so held-out rows are
back-propagated through, and the early stop that reads `test_mask`.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from sklearn.metrics import accuracy_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.loader import NeighborLoader
from torch_geometric.nn import SAGEConv

EPOCHS = 30
FANOUT = [15, 10]
BATCH_SIZE = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class SAGE(nn.Module):
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


dataset = Planetoid(root="data/Planetoid", name="Cora")
data = dataset[0]

# DEFECT: the training loader does not shuffle its seed nodes, so every epoch
# walks the graph in Planetoid's node order and the batches stay correlated.
# DEFECT: num_workers=4 with no `if __name__ == "__main__":` guard anywhere in
# this module, which deadlocks or re-imports under spawn.
# DEFECT: input_nodes is the whole graph rather than data.train_mask, so the
# training loss is computed over validation and test nodes as well.
train_loader = NeighborLoader(data, num_neighbors=FANOUT, batch_size=BATCH_SIZE,
                              shuffle=False, num_workers=4)
# DEFECT: the validation loader shuffles, so predictions no longer line up with
# the nodes they came from.
val_loader = NeighborLoader(data, num_neighbors=FANOUT, batch_size=BATCH_SIZE,
                            input_nodes=data.val_mask, shuffle=True,
                            num_workers=2)
test_loader = NeighborLoader(data, num_neighbors=FANOUT, batch_size=BATCH_SIZE,
                             input_nodes=data.test_mask, shuffle=False,
                             num_workers=2)


def train_epoch(model, loader, optimizer) -> float:
    model.train()
    running = 0.0
    batches = 0
    for batch in loader:
        batch = batch.to(DEVICE)
        logits = model(batch.x, batch.edge_index)
        seeds = batch.batch_size
        loss = F.cross_entropy(logits[:seeds], batch.y[:seeds])
        # DEFECT: the gradients are never zeroed, so every step applies the sum
        # of every batch since the run started.
        loss.backward()
        optimizer.step()
        running += loss.item()
        batches += 1
    return running / max(batches, 1)


def evaluate(model, loader) -> float:
    """DEFECT: no model.eval() and no torch.no_grad(), so the 0.5 dropout is
    still active and the whole pass builds an autograd graph."""
    predicted = []
    truth = []
    for batch in loader:
        batch = batch.to(DEVICE)
        logits = model(batch.x, batch.edge_index)
        seeds = batch.batch_size
        # DEFECT: the raw logits are handed to accuracy_score instead of the
        # argmax class, so the metric compares float scores to integer labels.
        predicted.append(logits[:seeds].detach().cpu())
        truth.append(batch.y[:seeds].cpu())
    return float(accuracy_score(torch.cat(truth).numpy(),
                                torch.cat(predicted).numpy()))


def main() -> None:
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    model = SAGE(dataset.num_features, 128, dataset.num_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    best = 0.0
    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_loader, optimizer)
        # DEFECT: model selection reads the TEST loader, so the reported test
        # accuracy is the maximum over thirty draws of the held-out set.
        score = evaluate(model, test_loader)
        if score > best:
            best = score
            torch.save(model, "sage_best.pt")
        print("epoch %d loss %.4f test %.4f" % (epoch, loss, score))

    # DEFECT: torch.load with neither weights_only nor map_location.
    model = torch.load("sage_best.pt")
    print("final test accuracy %.4f" % evaluate(model, test_loader))


main()
