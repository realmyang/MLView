"""The same pose trainer with eight planted defects.

Two of them are the ones that make a pose model look merely mediocre rather
than broken: the horizontal-flip augmentation no longer swaps the left/right
joint channels (in dataset.py), and the flip test at evaluation averages the
mirrored heatmaps without un-swapping them.
"""

from __future__ import annotations

import argparse
import json
import os
import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from dataset import (FLIP_PAIRS, KeypointDataset, decode_heatmaps, pck_at)
from model import PoseHighResolutionNet


class JointsMSELoss(nn.Module):
    """Per-joint MSE weighted by visibility - the standard heatmap objective."""

    def __init__(self, use_target_weight: bool = True) -> None:
        super().__init__()
        self.criterion = nn.MSELoss(reduction="mean")
        self.use_target_weight = use_target_weight

    def forward(self, output: torch.Tensor, target: torch.Tensor,
                target_weight: torch.Tensor) -> torch.Tensor:
        batch, joints = output.shape[0], output.shape[1]
        predicted = output.reshape(batch, joints, -1).split(1, 1)
        expected = target.reshape(batch, joints, -1).split(1, 1)
        total = 0.0
        for index in range(joints):
            left = predicted[index].squeeze(1)
            right = expected[index].squeeze(1)
            if self.use_target_weight:
                total = total + 0.5 * self.criterion(
                    left.mul(target_weight[:, index]),
                    right.mul(target_weight[:, index]))
            else:
                total = total + 0.5 * self.criterion(left, right)
        return total / joints


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_annotations(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_loaders(args):
    train_set = KeypointDataset(os.path.join(args.data, "images"),
                                load_annotations(os.path.join(args.data,
                                                              "train.json")),
                                train=True)
    # DEFECT: the validation dataset is constructed with train=True, so the
    # random scale, the random rotation and the random flip are all applied to
    # the split the PCK is reported on.
    val_set = KeypointDataset(os.path.join(args.data, "images"),
                              load_annotations(os.path.join(args.data, "val.json")),
                              train=True)
    # DEFECT: the training loader does not shuffle. COCO person crops are
    # written image by image, so consecutive batches are the same scene.
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=False,
                              num_workers=args.workers, pin_memory=True,
                              drop_last=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    return train_loader, val_loader


def train_one_epoch(model, loader, criterion, optimizer, scheduler, device, epoch):
    model.train()
    running = 0.0
    seen = 0
    for images, targets, weights, _meta in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        weights = weights.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        outputs = model(images)
        loss = criterion(outputs, targets, weights)
        loss.backward()
        optimizer.step()
        # DEFECT: MultiStepLR is an epoch schedule. Stepped once per batch it
        # blows through the milestones at 170 and 200 inside the first epoch.
        scheduler.step()

        # DEFECT: the running loss keeps the live tensor.
        running += loss * images.size(0)
        seen += images.size(0)
    return running / max(1, seen)


def validate(model, loader, criterion, device, flip_test: bool = True):
    # DEFECT: no model.eval(), so every BatchNorm2d in the stem, the branches
    # and the fuse layer updates its running statistics from the validation
    # split - twice per image, because the flip test runs a second forward.
    # DEFECT: no @torch.no_grad(), so two full graphs per batch are built.
    total_loss = 0.0
    total_pck = 0.0
    seen = 0
    for images, targets, weights, _meta in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        weights = weights.to(device, non_blocking=True)

        outputs = model(images)
        if flip_test:
            # DEFECT: the mirrored heatmaps are averaged in without swapping
            # the left/right channels back, so every paired joint is averaged
            # with its opposite and the peaks move toward the body midline.
            mirrored = model(images.flip(dims=[3]))
            outputs = (outputs + mirrored.flip(dims=[3])) * 0.5
        total_loss += criterion(outputs, targets, weights).item() * images.size(0)

        predicted, _scores = decode_heatmaps(outputs)
        expected, _ = decode_heatmaps(targets)
        total_pck += pck_at(predicted, expected, weights) * images.size(0)
        seen += images.size(0)
    return total_loss / max(1, seen), total_pck / max(1, seen)


def parse_args():
    parser = argparse.ArgumentParser(description="Top-down keypoint estimation")
    parser.add_argument("--data", default="data/coco")
    parser.add_argument("--epochs", type=int, default=210)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2023)
    parser.add_argument("--out", default="runs/pose")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args)
    model = PoseHighResolutionNet(width=32).to(device)
    criterion = JointsMSELoss(use_target_weight=True).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.MultiStepLR(
        optimizer, milestones=[170, 200], gamma=0.1)

    best = 0.0
    for epoch in range(args.epochs):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer,
                                     scheduler, device, epoch)
        val_loss, pck = validate(model, val_loader, criterion, device)
        print("epoch %d train %.5f val %.5f pck %.4f"
              % (epoch, train_loss, val_loss, pck))
        if pck > best:
            best = pck
            # DEFECT: the whole module is pickled rather than its state_dict.
            torch.save(model, os.path.join(args.out, "best.pt"))
    print("best pck %.4f" % best)


if __name__ == "__main__":
    main()
