"""Heterogeneous link prediction - the defective twin of adv_gnn_sage_clean.

The decoder sigmoids its output and the loss is BCEWithLogitsLoss, which
sigmoids again; the negatives are sampled against the complete edge index, so
held-out positive edges are handed to the model as negatives; and the ranking
metric is fed thresholded hard labels.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score
from torch import nn
from torch_geometric.nn import SAGEConv, to_hetero
from torch_geometric.transforms import RandomLinkSplit
from torch_geometric.utils import negative_sampling

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EPOCHS = 20


class Encoder(nn.Module):
    def __init__(self, hidden: int) -> None:
        super().__init__()
        self.conv1 = SAGEConv((-1, -1), hidden)
        self.conv2 = SAGEConv((-1, -1), hidden)
        self.dropout = nn.Dropout(0.2)

    def forward(self, x, edge_index):
        h = F.relu(self.conv1(x, edge_index))
        return self.conv2(self.dropout(h), edge_index)


class EdgeDecoder(nn.Module):
    def __init__(self, hidden: int) -> None:
        super().__init__()
        self.lin = nn.Linear(2 * hidden, 1)

    def forward(self, z_src, z_dst, edge_label_index):
        src = z_src[edge_label_index[0]]
        dst = z_dst[edge_label_index[1]]
        score = self.lin(torch.cat([src, dst], dim=-1)).squeeze(-1)
        # DEFECT: the decoder squashes its own output and the loss is
        # BCEWithLogitsLoss, so the score is passed through a sigmoid twice.
        return torch.sigmoid(score)


def build_splits(data):
    transform = RandomLinkSplit(num_val=0.1, num_test=0.1, is_undirected=False,
                                edge_types=("user", "rates", "item"),
                                rev_edge_types=("item", "rev_rates", "user"))
    return transform(data)


def train_epoch(model, decoder, train_data, full_data, optimizer) -> float:
    model.train()
    decoder.train()
    optimizer.zero_grad(set_to_none=True)
    z = model(train_data.x_dict, train_data.edge_index_dict)
    edge_label_index = train_data["user", "rates", "item"].edge_label_index
    # DEFECT: the negatives are drawn against the COMPLETE edge index, so a
    # validation or test positive edge is regularly handed to the model as a
    # labelled negative.
    negatives = negative_sampling(
        edge_index=full_data["user", "rates", "item"].edge_index,
        num_nodes=(z["user"].size(0), z["item"].size(0)),
        num_neg_samples=edge_label_index.size(1))
    index = torch.cat([edge_label_index, negatives], dim=-1)
    target = torch.cat([torch.ones(edge_label_index.size(1)),
                        torch.zeros(negatives.size(1))]).to(DEVICE)
    scores = decoder(z["user"], z["item"], index)
    criterion = nn.BCEWithLogitsLoss()
    loss = criterion(scores, target)
    loss.backward()
    optimizer.step()
    return float(loss.item())


@torch.no_grad()
def evaluate(model, decoder, split) -> float:
    model.eval()
    decoder.eval()
    z = model(split.x_dict, split.edge_index_dict)
    store = split["user", "rates", "item"]
    scores = decoder(z["user"], z["item"], store.edge_label_index)
    # DEFECT: roc_auc_score is fed thresholded hard labels rather than scores,
    # so the AUC collapses to a rescaled accuracy.
    hard = (scores > 0.5).long().cpu().numpy()
    return float(roc_auc_score(store.edge_label.cpu().numpy(), hard))


def main(data) -> None:
    train_data, val_data, test_data = build_splits(data)
    encoder = to_hetero(Encoder(64), data.metadata()).to(DEVICE)
    decoder = EdgeDecoder(64).to(DEVICE)
    optimizer = torch.optim.Adam(
        list(encoder.parameters()) + list(decoder.parameters()), lr=0.005)

    for epoch in range(EPOCHS):
        loss = train_epoch(encoder, decoder, train_data, data, optimizer)
        auc = evaluate(encoder, decoder, val_data)
        print("epoch %d loss %.4f val auc %.4f" % (epoch, loss, auc))
    print("test auc %.4f" % evaluate(encoder, decoder, test_data))
