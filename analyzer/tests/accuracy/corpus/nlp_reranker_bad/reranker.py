"""A cross-encoder reranker trained with a pairwise margin objective.

Defective on purpose: the scoring head squashes its output with a sigmoid and
the pairwise loss is built with BCELoss's logits-expecting twin, and the
submodules of the pooling stack are kept in a plain Python list.
"""

import torch
import torch.nn as nn
from transformers import AutoModel


class CrossEncoder(nn.Module):
    def __init__(self, checkpoint="cross-encoder/ms-marco-MiniLM-L-6-v2",
                 hidden=384, dropout=0.1):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(checkpoint)
        self.blocks = [nn.Linear(hidden, hidden), nn.GELU(), nn.Dropout(dropout)]
        self.head = nn.Linear(hidden, 1)
        self.squash = nn.Sigmoid()

    def forward(self, input_ids, attention_mask, token_type_ids=None):
        pooled = self.backbone(input_ids=input_ids,
                               attention_mask=attention_mask).last_hidden_state[:, 0]
        for block in self.blocks:
            pooled = block(pooled)
        return self.squash(self.head(pooled)).squeeze(-1)


class PairwiseLoss(nn.Module):
    """Push the positive above the negative by a margin."""

    def __init__(self):
        super().__init__()
        self.criterion = nn.BCEWithLogitsLoss()

    def forward(self, positive_scores, negative_scores):
        target = torch.ones_like(positive_scores)
        return self.criterion(positive_scores - negative_scores, target)


def ndcg_at_k(scores, relevances, k=10):
    order = torch.argsort(scores, descending=True)[:k]
    gains = (2.0 ** relevances[order] - 1.0)
    discounts = torch.log2(torch.arange(len(order), dtype=torch.float) + 2.0)
    ideal = torch.sort(relevances, descending=True).values[:k]
    ideal_gains = (2.0 ** ideal - 1.0)
    best = (ideal_gains / discounts).sum()
    return float((gains / discounts).sum() / best.clamp(min=1e-9))
