"""CRNN + CTC training, written the way the reference OCR repositories write it.

The one shape worth reading twice: `F.log_softmax` in front of `nn.CTCLoss` is
*required*, not a mistake. CTC consumes log-probabilities and applies no
normalisation of its own, so the pairing that would be a defect for
`CrossEntropyLoss` is the correct pairing here.
"""

from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from dataset import (ALPHABET, BLANK_INDEX, TextLineDataset, character_error_rate,
                     ctc_collate, decode, eval_transform, train_transform)
from model import build_model, count_parameters

NUM_CLASSES = len(ALPHABET) + 1  # + the blank


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(root: str, batch_size: int, workers: int):
    train_set = TextLineDataset(os.path.join(root, "train"),
                                transform=train_transform())
    val_set = TextLineDataset(os.path.join(root, "val"),
                              transform=eval_transform())
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True,
                              num_workers=workers, collate_fn=ctc_collate,
                              pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False,
                            num_workers=workers, collate_fn=ctc_collate,
                            pin_memory=True)
    return train_loader, val_loader


def train_one_epoch(model, loader, criterion, optimizer, scheduler, device, epoch):
    model.train()
    running_loss = 0.0
    seen = 0
    for images, targets, target_lengths, widths, _texts in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        target_lengths = target_lengths.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        # (N, T, C) -> (T, N, C) log-probabilities, which is CTC's layout
        log_probs = F.log_softmax(logits, dim=2).permute(1, 0, 2)
        input_lengths = torch.tensor(
            [model.downsampled_width(int(w)) for w in widths],
            dtype=torch.long, device=device)
        loss = criterion(log_probs, targets, input_lengths, target_lengths)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        scheduler.step()

        running_loss += loss.item() * images.size(0)
        seen += images.size(0)
    return running_loss / max(1, seen)


@torch.no_grad()
def validate(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    total_cer = 0.0
    samples = 0
    for images, targets, target_lengths, widths, texts in loader:
        images = images.to(device, non_blocking=True)
        flat_targets = targets.to(device, non_blocking=True)
        lengths = target_lengths.to(device, non_blocking=True)

        logits = model(images)
        log_probs = F.log_softmax(logits, dim=2).permute(1, 0, 2)
        input_lengths = torch.tensor(
            [model.downsampled_width(int(w)) for w in widths],
            dtype=torch.long, device=device)
        total_loss += criterion(log_probs, flat_targets, input_lengths,
                                lengths).item() * images.size(0)

        predictions = log_probs.argmax(dim=2).permute(1, 0).cpu()
        for row, truth in zip(predictions, texts):
            total_cer += character_error_rate(decode(row.tolist()), truth)
        samples += images.size(0)
    model.train()
    return total_loss / max(1, samples), total_cer / max(1, samples)


def save_checkpoint(model, optimizer, epoch, cer, path):
    torch.save({"model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "epoch": epoch,
                "cer": cer,
                "alphabet": ALPHABET}, path)


def parse_args():
    parser = argparse.ArgumentParser(description="CRNN/CTC text recognition")
    parser.add_argument("--data", default="data/lines")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--out", default="runs/crnn")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args.data, args.batch_size, args.workers)
    model = build_model(NUM_CLASSES).to(device)
    print("trainable parameters: %d" % count_parameters(model))

    criterion = nn.CTCLoss(blank=BLANK_INDEX, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr, epochs=args.epochs,
        steps_per_epoch=max(1, len(train_loader)))

    best_cer = float("inf")
    for epoch in range(args.epochs):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer,
                                     scheduler, device, epoch)
        val_loss, val_cer = validate(model, val_loader, criterion, device)
        print("epoch %d train %.4f val %.4f cer %.4f"
              % (epoch, train_loss, val_loss, val_cer))
        if val_cer < best_cer:
            best_cer = val_cer
            save_checkpoint(model, optimizer, epoch, val_cer,
                            os.path.join(args.out, "best.pt"))
    print("best character error rate: %.4f" % best_cer)


if __name__ == "__main__":
    main()
