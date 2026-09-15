"""FixMatch: supervised loss on the labelled batch, consistency loss on the
confident half of the unlabelled batch, and an EMA copy of the weights for
evaluation.

Three shapes here look like defects and are not:

* the EMA update runs under `torch.no_grad()` and touches every parameter in
  place - that is the only correct way to maintain a shadow model;
* the pseudo-label is computed under `no_grad()` inside the training step, in
  the middle of a loop that does back-propagate;
* `model.train()` stays on for the whole step while `ema_model.eval()` is the
  thing that is evaluated.
"""

from __future__ import annotations

import argparse
import copy
import math
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from data import (ImageListDataset, TwoViewDataset, eval_transform, interleave,
                  read_manifest, stratified_label_subset, strong_transform,
                  weak_transform)
from model import WideResNet


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class ModelEMA:
    """An exponential moving average of the student's weights."""

    def __init__(self, model: nn.Module, decay: float = 0.999) -> None:
        self.decay = decay
        self.module = copy.deepcopy(model)
        self.module.eval()
        for parameter in self.module.parameters():
            parameter.requires_grad_(False)

    @torch.no_grad()
    def update(self, model: nn.Module) -> None:
        student = dict(model.named_parameters())
        for name, shadow in self.module.named_parameters():
            shadow.mul_(self.decay).add_(student[name].detach(), alpha=1.0 - self.decay)
        student_buffers = dict(model.named_buffers())
        for name, shadow in self.module.named_buffers():
            shadow.copy_(student_buffers[name])


def build_loaders(args, rng):
    rows = read_manifest(os.path.join(args.data, "train.tsv"))
    labelled_rows, unlabelled_rows = stratified_label_subset(
        rows, args.labels_per_class, args.num_classes, rng)
    val_rows = read_manifest(os.path.join(args.data, "val.tsv"))

    labelled = ImageListDataset(labelled_rows, transform=weak_transform())
    unlabelled = TwoViewDataset(unlabelled_rows, weak_transform(), strong_transform())
    validation = ImageListDataset(val_rows, transform=eval_transform())

    labelled_loader = DataLoader(labelled, batch_size=args.batch_size, shuffle=True,
                                 num_workers=args.workers, drop_last=True,
                                 pin_memory=True)
    unlabelled_loader = DataLoader(unlabelled,
                                   batch_size=args.batch_size * args.mu,
                                   shuffle=True, num_workers=args.workers,
                                   drop_last=True, pin_memory=True)
    val_loader = DataLoader(validation, batch_size=args.batch_size * 2,
                            shuffle=False, num_workers=args.workers,
                            pin_memory=True)
    return labelled_loader, unlabelled_loader, val_loader


def cosine_schedule(optimizer, total_steps: int, warmup: int = 0):
    def factor(step: int) -> float:
        if step < warmup:
            return float(step) / float(max(1, warmup))
        progress = float(step - warmup) / float(max(1, total_steps - warmup))
        return max(0.0, math.cos(math.pi * 7.0 / 16.0 * progress))
    return torch.optim.lr_scheduler.LambdaLR(optimizer, factor)


def train_one_epoch(model, ema, labelled_loader, unlabelled_loader, optimizer,
                    scheduler, device, args):
    model.train()
    unlabelled_iterator = iter(unlabelled_loader)
    supervised_total = 0.0
    consistency_total = 0.0
    batches = 0
    for images_x, targets_x in labelled_loader:
        try:
            weak_u, strong_u = next(unlabelled_iterator)
        except StopIteration:
            unlabelled_iterator = iter(unlabelled_loader)
            weak_u, strong_u = next(unlabelled_iterator)

        images_x = images_x.to(device, non_blocking=True)
        targets_x = targets_x.to(device, non_blocking=True)
        weak_u = weak_u.to(device, non_blocking=True)
        strong_u = strong_u.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        batch = interleave(torch.cat((images_x, weak_u, strong_u)), 2 * args.mu + 1)
        logits = model(batch)
        logits = interleave(logits, 2 * args.mu + 1)
        logits_x = logits[: images_x.size(0)]
        logits_weak, logits_strong = logits[images_x.size(0):].chunk(2)

        supervised = F.cross_entropy(logits_x, targets_x, reduction="mean")
        with torch.no_grad():
            probabilities = torch.softmax(logits_weak.detach() / args.temperature, dim=-1)
            confidence, pseudo = probabilities.max(dim=-1)
            mask = confidence.ge(args.threshold).float()
        consistency = (F.cross_entropy(logits_strong, pseudo, reduction="none")
                       * mask).mean()
        loss = supervised + args.lambda_u * consistency
        loss.backward()
        optimizer.step()
        scheduler.step()
        ema.update(model)

        supervised_total += supervised.item()
        consistency_total += consistency.item()
        batches += 1
    return supervised_total / max(1, batches), consistency_total / max(1, batches)


@torch.no_grad()
def evaluate(module, loader, device):
    module.eval()
    correct = 0
    seen = 0
    loss_total = 0.0
    for images, targets in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        logits = module(images)
        loss_total += F.cross_entropy(logits, targets).item() * images.size(0)
        correct += (logits.argmax(dim=1) == targets).sum().item()
        seen += images.size(0)
    return loss_total / max(1, seen), correct / max(1, seen)


def parse_args():
    parser = argparse.ArgumentParser(description="FixMatch semi-supervised training")
    parser.add_argument("--data", default="data/cifar10")
    parser.add_argument("--epochs", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--mu", type=int, default=7)
    parser.add_argument("--lr", type=float, default=0.03)
    parser.add_argument("--threshold", type=float, default=0.95)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--lambda-u", type=float, default=1.0)
    parser.add_argument("--labels-per-class", type=int, default=25)
    parser.add_argument("--num-classes", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=5)
    parser.add_argument("--out", default="runs/fixmatch")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    rng = np.random.default_rng(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    labelled_loader, unlabelled_loader, val_loader = build_loaders(args, rng)
    model = WideResNet(depth=28, widen_factor=2,
                       num_classes=args.num_classes).to(device)
    ema = ModelEMA(model, decay=0.999)
    ema.module.to(device)

    optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=0.9,
                                weight_decay=5e-4, nesterov=True)
    scheduler = cosine_schedule(optimizer,
                                total_steps=args.epochs * max(1, len(labelled_loader)))

    best = 0.0
    for epoch in range(args.epochs):
        supervised, consistency = train_one_epoch(
            model, ema, labelled_loader, unlabelled_loader, optimizer, scheduler,
            device, args)
        _student_loss, student_accuracy = evaluate(model, val_loader, device)
        _ema_loss, ema_accuracy = evaluate(ema.module, val_loader, device)
        print("epoch %d sup %.4f cons %.4f student %.4f ema %.4f"
              % (epoch, supervised, consistency, student_accuracy, ema_accuracy))
        if ema_accuracy > best:
            best = ema_accuracy
            torch.save({"model": model.state_dict(),
                        "ema": ema.module.state_dict(),
                        "epoch": epoch,
                        "accuracy": ema_accuracy},
                       os.path.join(args.out, "best.pt"))
    print("best ema accuracy %.4f" % best)


if __name__ == "__main__":
    main()
