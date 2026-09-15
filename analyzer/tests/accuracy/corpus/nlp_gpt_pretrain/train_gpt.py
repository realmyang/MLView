"""Pre-train MiniGPT on a memory-mapped token stream.

Gradient accumulation, a cosine schedule, AMP, `torch.compile` and a checkpoint
resume — the five things a from-scratch loop always has, and four of the five
are wired wrong here.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from model import BLOCK_SIZE, MiniGPT

ACCUM_STEPS = 4
EPOCHS = 2
MAX_LR = 6e-4
CHECKPOINT = "runs/gpt/ckpt.pt"


def token_stream(path: str, batch_size: int = 12):
    tokens = np.load(path)
    usable = (len(tokens) - 1) // BLOCK_SIZE * BLOCK_SIZE
    inputs = torch.from_numpy(tokens[:usable].reshape(-1, BLOCK_SIZE))
    targets = torch.from_numpy(tokens[1:usable + 1].reshape(-1, BLOCK_SIZE))
    train_dataset = TensorDataset(inputs, targets)
    train_loader = DataLoader(train_dataset, batch_size=batch_size,
                              shuffle=True, drop_last=True)
    return train_loader


def build():
    model = MiniGPT()
    model = torch.compile(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=MAX_LR,
                                  betas=(0.9, 0.95), weight_decay=0.1)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    scaler = torch.amp.GradScaler("cuda")
    return model, optimizer, scheduler, scaler


def resume(model, optimizer):
    state = torch.load(CHECKPOINT)
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    return state["step"]


def train(train_loader, device="cuda"):
    model, optimizer, scheduler, scaler = build()
    model.to(device)
    model.train()
    total_loss = 0.0
    for epoch in range(EPOCHS):
        for step, (inputs, targets) in enumerate(train_loader):
            inputs = inputs.to(device)
            targets = targets.to(device)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits, loss = model(inputs, targets)
                loss = loss / ACCUM_STEPS
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM_STEPS == 0:
                optimizer.step()
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            scheduler.step()
            total_loss += loss
        print("epoch", epoch, "mean loss", total_loss / max(step, 1))
    torch.save(model, CHECKPOINT)
    return model


def main(path: str = "data/tokens.npy"):
    loader = token_stream(path)
    train(loader)


main()
