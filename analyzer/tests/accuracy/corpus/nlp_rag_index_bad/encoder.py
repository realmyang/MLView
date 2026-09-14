"""A pooled transformer encoder used for both the corpus and the queries.

Defective twin of `nlp_rag_index/encoder.py`: the encoding pass keeps the
autograd graph alive and the model is never put in eval mode, so every vector
in the index is produced through a randomly thinned network.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

CHECKPOINT = "sentence-transformers/all-MiniLM-L6-v2"
MAX_LENGTH = 256


class PooledEncoder(nn.Module):
    """Mean-pool the last hidden state over the attention mask, then normalise."""

    def __init__(self, checkpoint=CHECKPOINT, out_dim=384):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(checkpoint)
        self.dropout = nn.Dropout(0.1)
        self.projection = nn.Linear(self.backbone.config.hidden_size, out_dim)

    def forward(self, input_ids, attention_mask):
        hidden = self.backbone(input_ids=input_ids,
                               attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).float()
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
        return F.normalize(self.projection(self.dropout(pooled)), dim=-1)


def load_tokenizer(checkpoint=CHECKPOINT):
    return AutoTokenizer.from_pretrained(checkpoint)


def tokenize(tokenizer, texts, device):
    batch = tokenizer(texts, padding=True, truncation=True,
                      max_length=MAX_LENGTH, return_tensors="pt")
    return {key: value.to(device) for key, value in batch.items()}


def encode_texts(model, tokenizer, texts, device, batch_size=64):
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = tokenize(tokenizer, texts[start:start + batch_size], device)
        vectors.append(model(batch["input_ids"], batch["attention_mask"]).cpu())
    return torch.cat(vectors).detach().numpy()
