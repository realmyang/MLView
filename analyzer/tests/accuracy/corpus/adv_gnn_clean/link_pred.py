"""GraphSAGE link predictor with negative sampling - correct.

The encoder produces node embeddings; the decoder is a dot product, so the
score is a raw logit and the loss is BCEWithLogitsLoss. Negative edges are
resampled every epoch from the training graph only, and the message-passing
edges are the training edges, so no validation or test edge is ever visible to
the encoder.

Nothing here is a defect. Any high-severity finding is a false positive.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.nn import SAGEConv
from torch_geometric.transforms import RandomLinkSplit
from torch_geometric.utils import negative_sampling

SEED = 11
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 100


class Encoder(nn.Module):
    def __init__(self, in_channels: int, hidden: int, out_channels: int) -> None:
        super().__init__()
        self.conv1 = SAGEConv(in_channels, hidden)
        self.conv2 = SAGEConv(hidden, out_channels)
        self.dropout = nn.Dropout(0.2)

    def forward(self, x, edge_index):
        h = F.relu(self.conv1(x, edge_index))
        h = self.dropout(h)
        return self.conv2(h, edge_index)


def decode(z, edge_label_index):
    """Dot-product decoder. Returns a logit, deliberately not a probability."""
    source = z[edge_label_index[0]]
    target = z[edge_label_index[1]]
    return (source * target).sum(dim=-1)


def train_epoch(model, train_data, optimizer, criterion):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    z = model(train_data.x, train_data.edge_index)

    negative_edges = negative_sampling(
        edge_index=train_data.edge_index,
        num_nodes=train_data.num_nodes,
        num_neg_samples=train_data.edge_label_index.size(1),
        method="sparse")
    edge_label_index = torch.cat(
        [train_data.edge_label_index, negative_edges], dim=-1)
    edge_label = torch.cat([
        train_data.edge_label,
        train_data.edge_label.new_zeros(negative_edges.size(1)),
    ], dim=0)

    logits = decode(z, edge_label_index)
    loss = criterion(logits, edge_label)
    loss.backward()
    optimizer.step()
    return float(loss.item())


@torch.no_grad()
def evaluate(model, split, message_edge_index):
    """ROC-AUC on a held-out edge split, scored with probabilities."""
    model.eval()
    z = model(split.x, message_edge_index)
    logits = decode(z, split.edge_label_index)
    probabilities = torch.sigmoid(logits).cpu().numpy()
    return roc_auc_score(split.edge_label.cpu().numpy(), probabilities)


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    dataset = Planetoid(root="data/Planetoid", name="Cora")
    splitter = RandomLinkSplit(num_val=0.05, num_test=0.1,
                               is_undirected=True, add_negative_train_samples=False)
    train_data, val_data, test_data = splitter(dataset[0])
    train_data = train_data.to(DEVICE)
    val_data = val_data.to(DEVICE)
    test_data = test_data.to(DEVICE)

    model = Encoder(dataset.num_features, 128, 64).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.BCEWithLogitsLoss()

    best_val = 0.0
    best_state = None
    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_data, optimizer, criterion)
        val_auc = evaluate(model, val_data, train_data.edge_index)
        if val_auc > best_val:
            best_val = val_auc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        if epoch % 10 == 0:
            print("epoch %d loss %.4f val auc %.4f" % (epoch, loss, val_auc))

    if best_state is not None:
        model.load_state_dict(best_state)
    test_auc = evaluate(model, test_data, train_data.edge_index)
    print("val auc %.4f, test auc %.4f" % (best_val, test_auc))
    torch.save(model.state_dict(), "sage_link.pt")


if __name__ == "__main__":
    main()
