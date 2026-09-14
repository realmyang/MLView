"""A mean-pooled sentence encoder trained with an in-batch contrastive loss.

The head returns a similarity *logit* per pair; the loss chosen for it in
`contrastive_train.py` expects a probability, which is the planted mismatch.
"""
from __future__ import annotations

import torch
import torch.nn as nn

VOCAB_SIZE = 32000
EMBED_DIM = 384
PAD_INDEX = 0


def mean_pool(hidden, attention_mask):
    mask = attention_mask.unsqueeze(-1).float()
    summed = (hidden * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


class SentenceEncoder(nn.Module):
    def __init__(self, embed_dim: int = EMBED_DIM, layers: int = 4, heads: int = 6):
        super().__init__()
        self.embedding = nn.Embedding(VOCAB_SIZE, embed_dim, padding_idx=PAD_INDEX)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim, nhead=heads, batch_first=True)
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=layers)
        self.projection = nn.Linear(embed_dim, embed_dim)
        self.norm = nn.LayerNorm(embed_dim)

    def encode(self, input_ids, attention_mask):
        hidden = self.encoder(self.embedding(input_ids),
                              src_key_padding_mask=attention_mask == 0)
        pooled = mean_pool(hidden, attention_mask)
        return self.norm(self.projection(pooled))

    def forward(self, left_ids, left_mask, right_ids, right_mask):
        left = self.encode(left_ids, left_mask)
        right = self.encode(right_ids, right_mask)
        scale = torch.tensor(20.0)
        similarity = torch.cosine_similarity(left, right, dim=-1) * scale
        return similarity
