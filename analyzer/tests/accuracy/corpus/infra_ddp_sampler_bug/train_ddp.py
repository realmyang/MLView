"""The same `torchrun` job as `infra_ddp_correct`, written the way it is
usually written the first time.

Three planted defects:

1. `train_sampler.set_epoch(epoch)` is never called, so every rank replays the
   identical permutation on every epoch — the run trains on the same batch
   order forever and the `shuffle=True` on the sampler buys nothing.
2. Every rank writes the checkpoint, so N processes race on one path.
3. `optimizer.zero_grad()` is missing from the step, so gradients accumulate
   across the whole epoch.

The first two have no rule in the catalog today; the third is MLV201, and it
is de-rated by the DDP framework gate.
"""
from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.distributed as dist
import torch.nn as nn
from torch.nn.parallel import DistributedDataParallel
from torch.utils.data import DataLoader, TensorDataset
from torch.utils.data.distributed import DistributedSampler

from model import ResidualMLP


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def setup_distributed() -> tuple[int, int, torch.device]:
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend=backend)
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
    else:
        device = torch.device("cpu")
    return rank, local_rank, device


def build_loaders(batch_size: int, workers: int):
    features = torch.randn(4096, 32)
    labels = torch.randint(0, 4, (4096,))
    train_set = TensorDataset(features[:3072], labels[:3072])
    val_set = TensorDataset(features[3072:], labels[3072:])

    train_sampler = DistributedSampler(train_set, shuffle=True, seed=13)
    val_sampler = DistributedSampler(val_set, shuffle=False, drop_last=False)
    train_loader = DataLoader(train_set, batch_size=batch_size,
                              sampler=train_sampler, num_workers=workers,
                              pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size,
                            sampler=val_sampler, num_workers=workers,
                            pin_memory=True)
    return train_loader, val_loader, train_sampler


def train_one_epoch(model, loader, optimizer, criterion, device) -> float:
    model.train()
    running = 0.0
    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        logits = model(images)
        loss = criterion(logits, targets)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        running += loss.item()
    return running / max(len(loader), 1)


@torch.no_grad()
def evaluate(model, loader, criterion, device) -> float:
    model.eval()
    correct = torch.zeros(1, device=device)
    seen = torch.zeros(1, device=device)
    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        logits = model(images)
        correct += (logits.argmax(dim=1) == targets).sum()
        seen += targets.numel()
    dist.all_reduce(correct, op=dist.ReduceOp.SUM)
    dist.all_reduce(seen, op=dist.ReduceOp.SUM)
    model.train()
    return (correct / seen).item()


def main() -> None:
    parser = argparse.ArgumentParser(description="torchrun DDP, written wrong")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--out", default="checkpoints/ddp.pt")
    args = parser.parse_args()

    seed_everything(args.seed)
    rank, local_rank, device = setup_distributed()

    model = ResidualMLP(in_features=32, classes=4).to(device)
    ddp_model = DistributedDataParallel(
        model, device_ids=[local_rank] if device.type == "cuda" else None)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(ddp_model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=args.epochs)

    train_loader, val_loader, train_sampler = build_loaders(args.batch_size,
                                                            args.workers)
    for epoch in range(args.epochs):
        loss = train_one_epoch(ddp_model, train_loader, optimizer, criterion,
                               device)
        accuracy = evaluate(ddp_model, val_loader, criterion, device)
        scheduler.step()
        print("rank %d epoch %d loss %.4f acc %.4f" % (rank, epoch, loss,
                                                       accuracy))
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        torch.save(ddp_model, args.out)

    dist.barrier()
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
