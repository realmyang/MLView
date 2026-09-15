"""GraphSAGE link predictor with negative sampling - the defective twin.

The encoder sees the whole graph including the validation and test edges, the
decoder squashes its score through a sigmoid and then hands it to
BCEWithLogitsLoss, the negative sampler is allowed to draw the held-out
positives, and the ranking metric is fed hard 0/1 labels.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score
from torch import nn
from torch_geometric.datasets import Planetoid
from torch_geometric.nn import SAGEConv
from torch_geometric.transforms import RandomLinkSplit
from torch_geometric.utils import negative_sampling

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
    source = z[edge_label_index[0]]
    target = z[edge_label_index[1]]
    score = (source * target).sum(dim=-1)
    # DEFECT: the score is squashed here and squashed again inside
    # BCEWithLogitsLoss, so the effective gradient vanishes.
    return torch.sigmoid(score)


def train_epoch(model, train_data, full_edge_index, optimizer, criterion):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    # DEFECT: message passing runs over the complete edge index, so the encoder
    # propagates along the very edges the model is asked to predict.
    z = model(train_data.x, full_edge_index)

    # DEFECT: negative sampling is given the training edges only, so held-out
    # positive edges are drawn as negatives and labelled 0.
    negative_edges = negative_sampling(
        edge_index=train_data.edge_index,
        num_nodes=train_data.num_nodes,
        num_neg_samples=train_data.edge_label_index.size(1))
    edge_label_index = torch.cat(
        [train_data.edge_label_index, negative_edges], dim=-1)
    edge_label = torch.cat([
        train_data.edge_label,
        train_data.edge_label.new_zeros(negative_edges.size(1)),
    ], dim=0)

    scores = decode(z, edge_label_index)
    loss = criterion(scores, edge_label)
    loss.backward()
    optimizer.step()
    return float(loss.item())


@torch.no_grad()
def evaluate(model, split, full_edge_index):
    model.eval()
    z = model(split.x, full_edge_index)
    scores = decode(z, split.edge_label_index)
    # DEFECT: the ranking metric is fed thresholded hard labels, so the AUC it
    # reports is the accuracy of one arbitrary operating point.
    hard = (scores > 0.5).float().cpu().numpy()
    return roc_auc_score(split.edge_label.cpu().numpy(), hard)


def main() -> None:
    dataset = Planetoid(root="data/Planetoid", name="Cora")
    splitter = RandomLinkSplit(num_val=0.05, num_test=0.1, is_undirected=True)
    train_data, val_data, test_data = splitter(dataset[0])
    full_edge_index = dataset[0].edge_index.to(DEVICE)
    train_data = train_data.to(DEVICE)
    test_data = test_data.to(DEVICE)

    model = Encoder(dataset.num_features, 128, 64).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.BCEWithLogitsLoss()

    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_data, full_edge_index, optimizer, criterion)
        if epoch % 10 == 0:
            print("epoch %d loss %.4f" % (epoch, loss))

    print("test auc %.4f" % evaluate(model, test_data, full_edge_index))


if __name__ == "__main__":
    main()
