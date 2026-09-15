"""Matrix factorisation with a BPR objective, in plain torch."""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class MatrixFactorization(nn.Module):
    def __init__(self, n_users: int, n_items: int, dim: int = 64):
        super().__init__()
        self.user_embedding = nn.Embedding(n_users, dim)
        self.item_embedding = nn.Embedding(n_items, dim)
        self.item_bias = nn.Embedding(n_items, 1)
        nn.init.normal_(self.user_embedding.weight, std=0.05)
        nn.init.normal_(self.item_embedding.weight, std=0.05)
        nn.init.zeros_(self.item_bias.weight)

    def score(self, users: torch.Tensor, items: torch.Tensor) -> torch.Tensor:
        dot = (self.user_embedding(users) * self.item_embedding(items)).sum(-1)
        return dot + self.item_bias(items).squeeze(-1)

    def forward(self, users, positives, negatives):
        return self.score(users, positives), self.score(users, negatives)


def bpr_loss(positive_scores: torch.Tensor,
             negative_scores: torch.Tensor) -> torch.Tensor:
    return -F.logsigmoid(positive_scores - negative_scores).mean()
