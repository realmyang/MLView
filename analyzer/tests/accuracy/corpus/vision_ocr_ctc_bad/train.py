"""The same CRNN/CTC recogniser with eight planted defects.

Every one of them is a mistake an OCR practitioner actually makes: the
photometric jitter left on the validation split, a validation loader that
shuffles so the printed sample predictions never line up twice, an evaluation
pass that forgot both `eval()` and `no_grad()`, a one-cycle schedule advanced
once per epoch, clipping moved after the step, the whole module pickled, and -
the one no rule models - `softmax` where CTC needs `log_softmax`.
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
    # DEFECT: the validation split is read through the augmenting pipeline, so
    # the reported character error rate is measured on jittered crops.
    val_set = TextLineDataset(os.path.join(root, "val"),
                              transform=train_transform())
    # DEFECT: the training loader does not shuffle. The crops are written in
    # page order, so each batch is one document and one font.
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=False,
                              num_workers=workers, collate_fn=ctc_collate,
                              pin_memory=True, drop_last=True)
    # DEFECT: the evaluation loader shuffles, so the sample predictions printed
    # after each epoch are a different set of lines every time.
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=True,
                            num_workers=workers, collate_fn=ctc_collate,
                            pin_memory=True)
    return train_loader, val_loader


def train_one_epoch(model, loader, criterion, optimizer, device, epoch):
    model.train()
    running_loss = 0.0
    seen = 0
    for images, targets, target_lengths, widths, _texts in loader:
        images = images.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        target_lengths = target_lengths.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        # DEFECT: CTC consumes log-probabilities. Plain softmax makes the loss
        # finite but wrong, and the model converges to all-blank.
        probs = F.softmax(logits, dim=2).permute(1, 0, 2)
        input_lengths = torch.tensor(
            [model.downsampled_width(int(w)) for w in widths],
            dtype=torch.long, device=device)
        loss = criterion(probs, targets, input_lengths, target_lengths)
        loss.backward()
        optimizer.step()
        # DEFECT: clipping runs after the update, so it never clips anything
        # that mattered.
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)

        # DEFECT: the running loss keeps the live tensor, so every batch's
        # autograd graph is retained for the whole epoch.
        running_loss += loss * images.size(0)
        seen += images.size(0)
    return running_loss / max(1, seen)


def validate(model, loader, criterion, device):
    # DEFECT: no model.eval(), so dropout stays on and every BatchNorm2d in the
    # backbone updates its running statistics from the validation split.
    # DEFECT: no torch.no_grad(), so the graph for the whole validation set is
    # built and thrown away.
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
    return total_loss / max(1, samples), total_cer / max(1, samples)


def save_checkpoint(model, optimizer, epoch, cer, path):
    # DEFECT: the whole module is pickled rather than its state_dict.
    torch.save(model, path)


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
                                     device, epoch)
        val_loss, val_cer = validate(model, val_loader, criterion, device)
        # DEFECT: OneCycleLR is a per-batch schedule. Stepped once an epoch it
        # spends the whole run in the warm-up ramp.
        scheduler.step()
        print("epoch %d train %.4f val %.4f cer %.4f"
              % (epoch, train_loss, val_loss, val_cer))
        if val_cer < best_cer:
            best_cer = val_cer
            save_checkpoint(model, optimizer, epoch, val_cer,
                            os.path.join(args.out, "best.pt"))
    print("best character error rate: %.4f" % best_cer)


if __name__ == "__main__":
    main()
