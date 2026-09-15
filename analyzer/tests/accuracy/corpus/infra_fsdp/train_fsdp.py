"""FSDP training of a small transformer block stack.

Written correctly: sharding policy, bf16 mixed precision, a sharded state-dict
save on rank 0, `set_epoch` on the sampler, and the usual zero_grad ->
forward -> backward -> clip -> step order. `FullyShardedDataParallel` shards
parameters; it does *not* write the training loop, so every training-loop rule
still applies to this file exactly as it would to a single-GPU script.

Any finding in this file is a false positive.
"""
from __future__ import annotations

import functools
import os
import random

import numpy as np
import torch
import torch.distributed as dist
import torch.nn as nn
from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
from torch.distributed.fsdp import MixedPrecision, ShardingStrategy, StateDictType
from torch.distributed.fsdp.wrap import transformer_auto_wrap_policy
from torch.utils.data import DataLoader, TensorDataset
from torch.utils.data.distributed import DistributedSampler

SEED = 2024
BLOCK_WIDTH = 256
DEPTH = 6


class EncoderBlock(nn.Module):
    def __init__(self, width: int = BLOCK_WIDTH, heads: int = 4) -> None:
        super().__init__()
        self.attention = nn.MultiheadAttention(width, heads, batch_first=True)
        self.norm1 = nn.LayerNorm(width)
        self.norm2 = nn.LayerNorm(width)
        self.mlp = nn.Sequential(
            nn.Linear(width, width * 4),
            nn.GELU(),
            nn.Linear(width * 4, width),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        normed = self.norm1(x)
        attended, _ = self.attention(normed, normed, normed, need_weights=False)
        x = x + attended
        return x + self.mlp(self.norm2(x))


class TinyEncoder(nn.Module):
    def __init__(self, vocab: int = 4096, width: int = BLOCK_WIDTH,
                 depth: int = DEPTH, classes: int = 8) -> None:
        super().__init__()
        self.embed = nn.Embedding(vocab, width)
        self.blocks = nn.ModuleList([EncoderBlock(width) for _ in range(depth)])
        self.norm = nn.LayerNorm(width)
        self.head = nn.Linear(width, classes)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        hidden = self.embed(tokens)
        for block in self.blocks:
            hidden = block(hidden)
        return self.head(self.norm(hidden).mean(dim=1))


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_loaders(batch_size: int, workers: int):
    tokens = torch.randint(0, 4096, (8192, 64))
    labels = torch.randint(0, 8, (8192,))
    train_set = TensorDataset(tokens[:6144], labels[:6144])
    val_set = TensorDataset(tokens[6144:], labels[6144:])
    train_sampler = DistributedSampler(train_set, shuffle=True, seed=SEED)
    val_sampler = DistributedSampler(val_set, shuffle=False)
    train_loader = DataLoader(train_set, batch_size=batch_size,
                              sampler=train_sampler, num_workers=workers,
                              pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size,
                            sampler=val_sampler, num_workers=workers)
    return train_loader, val_loader, train_sampler


def wrap(model: nn.Module, device: torch.device) -> FSDP:
    policy = functools.partial(transformer_auto_wrap_policy,
                               transformer_layer_cls={EncoderBlock})
    precision = MixedPrecision(param_dtype=torch.bfloat16,
                               reduce_dtype=torch.float32,
                               buffer_dtype=torch.bfloat16)
    return FSDP(model,
                auto_wrap_policy=policy,
                mixed_precision=precision,
                sharding_strategy=ShardingStrategy.FULL_SHARD,
                device_id=device.index if device.type == "cuda" else None,
                use_orig_params=True)


def save_sharded(model: FSDP, rank: int, path: str) -> None:
    with FSDP.state_dict_type(model, StateDictType.FULL_STATE_DICT):
        state = model.state_dict()
    if rank == 0:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(state, path)


def validate(model, loader, criterion, device) -> float:
    model.eval()
    total = torch.zeros(1, device=device)
    seen = torch.zeros(1, device=device)
    with torch.no_grad():
        for tokens, labels in loader:
            tokens = tokens.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            logits = model(tokens)
            total += criterion(logits, labels) * labels.numel()
            seen += labels.numel()
    dist.all_reduce(total, op=dist.ReduceOp.SUM)
    dist.all_reduce(seen, op=dist.ReduceOp.SUM)
    model.train()
    return (total / seen).item()


def main(epochs: int = 8, batch_size: int = 32, workers: int = 4,
         lr: float = 1e-4, out: str = "checkpoints/fsdp.pt") -> None:
    seed_all(SEED)
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    rank = int(os.environ.get("RANK", "0"))
    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend=backend)
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
    else:
        device = torch.device("cpu")

    model = wrap(TinyEncoder().to(device), device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.1)
    train_loader, val_loader, train_sampler = build_loaders(batch_size, workers)

    for epoch in range(epochs):
        model.train()
        train_sampler.set_epoch(epoch)
        for tokens, labels in train_loader:
            tokens = tokens.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(tokens), labels)
            loss.backward()
            model.clip_grad_norm_(1.0)
            optimizer.step()
        val_loss = validate(model, val_loader, criterion, device)
        if rank == 0:
            print("epoch %d val_loss %.4f" % (epoch, val_loss))
        save_sharded(model, rank, out)

    dist.destroy_process_group()


if __name__ == "__main__":
    main()
