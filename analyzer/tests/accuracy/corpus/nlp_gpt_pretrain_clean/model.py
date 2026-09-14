"""The correct twin of `nlp_gpt_pretrain/model.py`.

Every block chains its base initialiser, the block stack is an `nn.ModuleList`,
and the language-model head returns logits — `F.cross_entropy` applies the
log-softmax itself.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

BLOCK_SIZE = 256
VOCAB_SIZE = 50257


class CausalSelfAttention(nn.Module):
    def __init__(self, n_embd: int, n_head: int):
        super().__init__()
        self.n_head = n_head
        self.n_embd = n_embd
        self.qkv = nn.Linear(n_embd, 3 * n_embd, bias=False)
        self.proj = nn.Linear(n_embd, n_embd, bias=False)
        self.dropout = nn.Dropout(0.1)

    def forward(self, x):
        batch, time, channels = x.size()
        q, k, v = self.qkv(x).split(self.n_embd, dim=2)
        q = q.view(batch, time, self.n_head, channels // self.n_head).transpose(1, 2)
        k = k.view(batch, time, self.n_head, channels // self.n_head).transpose(1, 2)
        v = v.view(batch, time, self.n_head, channels // self.n_head).transpose(1, 2)
        attention = (q @ k.transpose(-2, -1)) / math.sqrt(k.size(-1))
        attention = attention.masked_fill(
            torch.tril(torch.ones(time, time)) == 0, float("-inf"))
        attention = attention.softmax(dim=-1)
        out = (attention @ v).transpose(1, 2).contiguous().view(batch, time, channels)
        return self.proj(self.dropout(out))


class Block(nn.Module):
    def __init__(self, n_embd: int, n_head: int):
        super().__init__()
        self.ln1 = nn.LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head)
        self.ln2 = nn.LayerNorm(n_embd)
        self.mlp = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd),
            nn.GELU(),
            nn.Linear(4 * n_embd, n_embd),
            nn.Dropout(0.1),
        )

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        return x + self.mlp(self.ln2(x))


class MiniGPT(nn.Module):
    def __init__(self, n_layer: int = 6, n_embd: int = 384, n_head: int = 6):
        super().__init__()
        self.token_embedding = nn.Embedding(VOCAB_SIZE, n_embd)
        self.position_embedding = nn.Embedding(BLOCK_SIZE, n_embd)
        self.blocks = nn.ModuleList([Block(n_embd, n_head) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(n_embd)
        self.lm_head = nn.Linear(n_embd, VOCAB_SIZE, bias=False)

    def forward(self, idx, targets=None):
        batch, time = idx.shape
        positions = torch.arange(time, device=idx.device)
        x = self.token_embedding(idx) + self.position_embedding(positions)
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            flat = logits.view(-1, VOCAB_SIZE)
            loss = F.cross_entropy(flat, targets.view(-1))
        return logits, loss
