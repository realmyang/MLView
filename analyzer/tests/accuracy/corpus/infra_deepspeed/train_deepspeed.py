"""A DeepSpeed ZeRO-2 trainer driven entirely by `ds_config.json`.

The engine owns the optimizer, the scheduler, the gradient accumulation and
the zeroing: the documented DeepSpeed step is exactly

    loss = model_engine(batch)
    model_engine.backward(loss)
    model_engine.step()

`model_engine.step()` zeroes the gradients itself, so there is deliberately no
`optimizer.zero_grad()` in this file and its absence is *not* a defect. An
MLV201 here is a false positive.

The batch size, the learning rate, the optimizer and the precision all live in
`ds_config.json` rather than in Python, which is the shape a config-driven
trainer has.
"""
from __future__ import annotations

import argparse
import json
import os

import deepspeed
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from torch.utils.data.distributed import DistributedSampler

from model import CaptionScorer


def load_ds_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_datasets(rows: int = 8192, features: int = 64):
    torch.manual_seed(7)
    x = torch.randn(rows, features)
    y = torch.randint(0, 5, (rows,))
    cut = int(rows * 0.9)
    return (TensorDataset(x[:cut], y[:cut]),
            TensorDataset(x[cut:], y[cut:]))


def evaluate(engine, loader, criterion, device) -> float:
    engine.eval()
    total = 0.0
    seen = 0
    with torch.no_grad():
        for features, labels in loader:
            features = features.to(device)
            labels = labels.to(device)
            logits = engine(features)
            total += criterion(logits, labels).item() * labels.numel()
            seen += labels.numel()
    engine.train()
    return total / max(seen, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSpeed ZeRO trainer")
    parser.add_argument("--deepspeed_config", default="ds_config.json")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--local_rank", type=int, default=-1)
    parser.add_argument("--save-dir", default="checkpoints/ds")
    parser = deepspeed.add_config_arguments(parser)
    args = parser.parse_args()

    config = load_ds_config(args.deepspeed_config)
    micro_batch = config["train_micro_batch_size_per_gpu"]

    train_set, val_set = build_datasets()
    model = CaptionScorer(in_features=64, classes=5)
    criterion = nn.CrossEntropyLoss()

    engine, optimizer, train_loader, scheduler = deepspeed.initialize(
        args=args,
        model=model,
        model_parameters=[p for p in model.parameters() if p.requires_grad],
        training_data=train_set,
        config=config,
    )
    device = engine.device

    val_sampler = DistributedSampler(val_set, shuffle=False)
    val_loader = DataLoader(val_set, batch_size=micro_batch,
                            sampler=val_sampler, num_workers=2)

    for epoch in range(args.epochs):
        engine.train()
        for features, labels in train_loader:
            features = features.to(device)
            labels = labels.to(device)
            logits = engine(features)
            loss = criterion(logits, labels)
            engine.backward(loss)
            engine.step()
        val_loss = evaluate(engine, val_loader, criterion, device)
        if engine.global_rank == 0:
            print("epoch %d val_loss %.4f" % (epoch, val_loss))
        os.makedirs(args.save_dir, exist_ok=True)
        engine.save_checkpoint(args.save_dir, tag="epoch-%d" % epoch)


if __name__ == "__main__":
    main()
