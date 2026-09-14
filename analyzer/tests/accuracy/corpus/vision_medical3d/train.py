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
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.workers, pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=1, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    return train_loader, val_loader


def build_model(args, device):
    return UNet(spatial_dims=3, in_channels=1, out_channels=args.num_classes,
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
        scaler.update()

        epoch_loss += loss.item()
        steps += 1
    return epoch_loss / max(1, steps)


@torch.no_grad()
def validate(model, loader, metric, post_prediction, post_label, device, args):
    model.eval()
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
    model.train()
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
    set_determinism(seed=args.seed)
    torch.manual_seed(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args)
    model = build_model(args, device)
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
                torch.save({"model": model.state_dict(), "epoch": epoch,
                            "dice": dice}, os.path.join(args.out, "best.pt"))
        else:
            print("epoch %d loss %.4f" % (epoch, loss))
    print("best mean dice %.4f" % best)


if __name__ == "__main__":
    main()
