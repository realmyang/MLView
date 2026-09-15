"""A hand-rolled LoRA adapter over a frozen causal language model.

The adapter itself is the interesting part: two low-rank projections per
attention matrix, held in a plain dict, which is the classic way to lose every
adapter parameter without any error being raised.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "gpt2-medium"
RANK = 8
ALPHA = 16
TARGETS = ("q_proj", "v_proj")


class LoRALinear(nn.Module):
    """y = W0 x + (alpha / r) * B(A x), with W0 frozen."""

    def __init__(self, in_features: int, out_features: int, rank: int = RANK):
        super().__init__()
        self.scaling = ALPHA / rank
        self.base = nn.Linear(in_features, out_features, bias=False)
        self.base.weight.requires_grad = False
        self.down = nn.Linear(in_features, rank, bias=False)
        self.up = nn.Linear(rank, out_features, bias=False)
        self.dropout = nn.Dropout(0.05)

    def forward(self, x):
        return self.base(x) + self.scaling * self.up(self.down(self.dropout(x)))


class AdapterStack(nn.Module):
    """One `LoRALinear` per targeted projection, keyed by name."""

    def __init__(self, hidden_size: int):
        super().__init__()
        self.adapters = {name: LoRALinear(hidden_size, hidden_size)
                         for name in TARGETS}

    def forward(self, name, x):
        return self.adapters[name](x)


def load_base():
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL)
    for parameter in model.parameters():
        parameter.requires_grad = False
    return tokenizer, model


def trainable_parameters(adapters: AdapterStack):
    return [p for p in adapters.parameters() if p.requires_grad]
