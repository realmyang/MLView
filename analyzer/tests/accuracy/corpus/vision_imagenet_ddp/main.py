"""The distributed entrypoint.

`torchrun --nproc_per_node=8 main.py` launches this; every worker re-imports
the module, so nothing but the guard at the bottom runs at import time.
"""

from __future__ import annotations

import os

import torch
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel

from config import CFG, checkpoint_path, pick_device, set_seed
from data import build_loaders
from engine import (build_optimizer, build_scheduler, evaluate, load_checkpoint,
                    make_scaler, save_checkpoint, train_one_epoch)
from model import ModelEma, build_criterion, build_model


def setup_distributed():
    """Return (distributed, rank, world_size, local_rank)."""
    if "RANK" not in os.environ or "WORLD_SIZE" not in os.environ:
        return False, 0, 1, 0
    rank = int(os.environ["RANK"])
    world_size = int(os.environ["WORLD_SIZE"])
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend=backend, rank=rank, world_size=world_size)
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
    return True, rank, world_size, local_rank


def teardown_distributed(distributed: bool) -> None:
    if distributed and dist.is_initialized():
        dist.destroy_process_group()


def is_primary(rank: int) -> bool:
    return rank == 0


def run() -> float:
    set_seed()
    distributed, rank, world_size, local_rank = setup_distributed()
    device = pick_device(local_rank)

    train_loader, val_loader, test_loader, train_sampler = build_loaders(
        distributed, rank=rank, world_size=world_size)

    model = build_model(classes=1000)
    model.to(device)
    if distributed:
        model = torch.nn.SyncBatchNorm.convert_sync_batchnorm(model)
        model = DistributedDataParallel(model, device_ids=[local_rank])

    ema = ModelEma(model)
    ema.to(device)
    criterion = build_criterion()
    optimizer = build_optimizer(model)
    scaler = make_scaler(device)
    scheduler = build_scheduler(optimizer, steps_per_epoch=len(train_loader))

    best_top1 = 0.0
    for epoch in range(CFG.epochs):
        if train_sampler is not None:
            train_sampler.set_epoch(epoch)
        train_loss = train_one_epoch(model, ema, train_loader, criterion,
                                     optimizer, scaler, scheduler, device, epoch)
        metrics = evaluate(ema, val_loader, criterion, device)
        if is_primary(rank):
            print("epoch %d train_loss %.4f val_top1 %.4f val_top5 %.4f"
                  % (epoch, train_loss, metrics["top1"], metrics["top5"]))
            if metrics["top1"] > best_top1:
                best_top1 = metrics["top1"]
                save_checkpoint(model, ema, optimizer, scaler, epoch, best_top1,
                                tag="best")
            save_checkpoint(model, ema, optimizer, scaler, epoch, best_top1,
                            tag="last")

    if is_primary(rank):
        load_checkpoint(checkpoint_path("best"), model, device)
        final = evaluate(model, test_loader, criterion, device)
        print("test top1 %.4f top5 %.4f" % (final["top1"], final["top5"]))
        best_top1 = final["top1"]

    teardown_distributed(distributed)
    return best_top1


if __name__ == "__main__":
    run()
