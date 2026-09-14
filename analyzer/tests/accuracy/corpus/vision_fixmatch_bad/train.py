"""The same FixMatch run with seven planted defects.

The two that matter most in this domain are the ones no rule models: the EMA
shadow is updated *before* the optimizer step, so it tracks the weights the
student is about to leave behind, and the confidence mask is read off the
*strong* view, which is the one view whose predictions are supposed to be
unreliable.
"""

from __future__ import annotations

import argparse
import copy
import math
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from data import (ImageListDataset, TwoViewDataset, eval_transform, interleave,
                  read_manifest, stratified_label_subset, strong_transform,
                  weak_transform)
from model import WideResNet


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
    # DEFECT: the validation split is read through the strong pipeline, so the
    # reported accuracy is measured on RandAugment-ed and Cutout-ed images.
    validation = ImageListDataset(val_rows, transform=strong_transform())

    labelled_loader = DataLoader(labelled, batch_size=args.batch_size, shuffle=True,
                                 num_workers=args.workers, drop_last=True,
                                 pin_memory=True)
    # DEFECT: the unlabelled loader does not shuffle. The pool is written in
    # class order, so every unlabelled batch is one class and the pseudo-label
    # distribution collapses onto it.
    unlabelled_loader = DataLoader(unlabelled,
                                   batch_size=args.batch_size * args.mu,
                                   shuffle=False, num_workers=args.workers,
                                   drop_last=True, pin_memory=True)
    # DEFECT: the evaluation loader shuffles.
    val_loader = DataLoader(validation, batch_size=args.batch_size * 2,
                            shuffle=True, num_workers=args.workers,
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
            # DEFECT: the pseudo-label and the confidence mask are taken from
            # the STRONG view. FixMatch's whole premise is that the weak view
            # is the reliable one; reading the strong view makes the model its
            # own noisy teacher and the training collapses to a single class.
            probabilities = torch.softmax(logits_strong.detach() / args.temperature,
                                          dim=-1)
            confidence, pseudo = probabilities.max(dim=-1)
            mask = confidence.ge(args.threshold).float()
        consistency = (F.cross_entropy(logits_strong, pseudo, reduction="none")
                       * mask).mean()
        loss = supervised + args.lambda_u * consistency
        loss.backward()
        # DEFECT: the shadow is updated before the step, so it averages the
        # weights the student is about to leave rather than the ones it reaches.
        ema.update(model)
        optimizer.step()
        scheduler.step()

        # DEFECT: both running totals keep the live tensors.
        supervised_total += supervised
        consistency_total += consistency
        batches += 1
    return supervised_total / max(1, batches), consistency_total / max(1, batches)


def evaluate(module, loader, device):
    # DEFECT: no module.eval(), so every BatchNorm2d in the WideResNet updates
    # its running statistics from the validation split before the next epoch.
    # DEFECT: no torch.no_grad(), so the graph for the whole validation set is
    # built and dropped.
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
    # DEFECT: nothing is seeded. The labelled subset is drawn at random, so the
    # 25-labels-per-class benchmark is a different benchmark on every run.
    rng = np.random.default_rng()
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
