"""MONAI 3-D UNet segmentation of abdominal CT, written the way the MONAI
tutorials write it.

Two shapes are worth naming. The validation pass uses `sliding_window_inference`
rather than a plain forward, because a 512x512x200 volume does not fit in
memory at once; and the Dice metric is accumulated inside a `DiceMetric` object
rather than as a Python running total, so there is no `+=` anywhere in the
evaluation loop.
"""

from __future__ import annotations

import argparse
import json
import os

import torch
from monai.data import CacheDataset, DataLoader, decollate_batch
from monai.inferers import sliding_window_inference
from monai.losses import DiceCELoss
from monai.metrics import DiceMetric
from monai.networks.nets import UNet
from monai.transforms import AsDiscrete
from monai.utils import set_determinism

from transforms_cfg import PATCH_SIZE, train_transforms, val_transforms


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def read_split(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["training"], payload["validation"]


def build_loaders(args):
    train_files, val_files = read_split(os.path.join(args.data, "dataset.json"))
    train_set = CacheDataset(data=train_files, transform=train_transforms(),
                             cache_rate=1.0, num_workers=args.workers)
    val_set = CacheDataset(data=val_files, transform=val_transforms(),
                           cache_rate=1.0, num_workers=args.workers)
    # DEFECT: the training loader does not shuffle. BTCV volumes are listed
    # patient by patient, so every batch is one abdomen.
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=False,
                              num_workers=args.workers, pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=1, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    return train_loader, val_loader


def build_model(args, device):
    # DEFECT: the head emits one channel while the loss one-hots 14 classes.
    return UNet(spatial_dims=3, in_channels=1, out_channels=1,
                channels=(16, 32, 64, 128, 256), strides=(2, 2, 2, 2),
                num_res_units=2, norm="instance").to(device)


def train_one_epoch(model, loader, criterion, optimizer, scaler, device, args):
    model.train()
    epoch_loss = 0.0
    steps = 0
    for batch in loader:
        images = batch["image"].to(device, non_blocking=True)
        labels = batch["label"].to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16,
                            enabled=args.amp):
            logits = model(images)
            loss = criterion(logits, labels)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        # DEFECT: scaler.update() is gone, so the loss scale never adapts and
        # the first overflow freezes the run.

        # DEFECT: the epoch loss keeps the live tensor.
        epoch_loss += loss
        steps += 1
    return epoch_loss / max(1, steps)


def validate(model, loader, metric, post_prediction, post_label, device, args):
    # DEFECT: no model.eval(), so every InstanceNorm3d and Dropout in the UNet
    # behaves as it does in training while the Dice is measured.
    # DEFECT: no @torch.no_grad(), so sliding_window_inference over a whole
    # 512x512x200 volume builds an autograd graph and runs out of memory.
    metric.reset()
    for batch in loader:
        images = batch["image"].to(device, non_blocking=True)
        labels = batch["label"].to(device, non_blocking=True)
        logits = sliding_window_inference(images, PATCH_SIZE, args.sw_batch_size,
                                          model, overlap=0.5)
        predictions = [post_prediction(item) for item in decollate_batch(logits)]
        references = [post_label(item) for item in decollate_batch(labels)]
        metric(y_pred=predictions, y=references)
    score = metric.aggregate().item()
    metric.reset()
    return score


def parse_args():
    parser = argparse.ArgumentParser(description="MONAI 3D UNet segmentation")
    parser.add_argument("--data", default="data/btcv")
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--sw-batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--num-classes", type=int, default=14)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--val-every", type=int, default=10)
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="runs/btcv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # DEFECT: nothing is seeded - both calls are gone.
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args)
    model = build_model(args, device)
    # DEFECT: softmax=True over a single output channel is identically 1, so
    # the Dice term has no gradient and only the cross-entropy half trains.
    criterion = DiceCELoss(to_onehot_y=True, softmax=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler(enabled=args.amp)

    metric = DiceMetric(include_background=False, reduction="mean",
                        get_not_nans=False)
    post_prediction = AsDiscrete(argmax=True, to_onehot=args.num_classes)
    post_label = AsDiscrete(to_onehot=args.num_classes)

    best = 0.0
    for epoch in range(args.epochs):
        loss = train_one_epoch(model, train_loader, criterion, optimizer,
                               scaler, device, args)
        scheduler.step()
        if (epoch + 1) % args.val_every == 0:
            dice = validate(model, val_loader, metric, post_prediction,
                            post_label, device, args)
            print("epoch %d loss %.4f dice %.4f" % (epoch, loss, dice))
            if dice > best:
                best = dice
                # DEFECT: the whole module is pickled.
                torch.save(model, os.path.join(args.out, "best.pt"))
        else:
            print("epoch %d loss %.4f" % (epoch, loss))
    print("best mean dice %.4f" % best)


if __name__ == "__main__":
    main()
