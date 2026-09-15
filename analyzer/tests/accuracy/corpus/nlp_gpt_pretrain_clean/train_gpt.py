"""The correct twin of `nlp_gpt_pretrain/train_gpt.py`.

Gradient accumulation zeroes on the accumulation boundary, the clip runs after
`unscale_` and before `scaler.step`, the cosine schedule advances once per
epoch, the loss is accumulated as a float, and the checkpoint is a state dict
loaded with `weights_only=True`.
"""
from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from model import BLOCK_SIZE, MiniGPT

ACCUM_STEPS = 4
EPOCHS = 2
MAX_LR = 6e-4
SEED = 1337
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


def train(train_loader, device):
    torch.manual_seed(SEED)
    model = MiniGPT()
    model = torch.compile(model)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=MAX_LR,
                                  betas=(0.9, 0.95), weight_decay=0.1)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    scaler = torch.amp.GradScaler("cuda")
    model.train()
    for epoch in range(EPOCHS):
        total_loss = 0.0
        for step, (inputs, targets) in enumerate(train_loader):
            inputs = inputs.to(device)
            targets = targets.to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits, loss = model(inputs, targets)
                loss = loss / ACCUM_STEPS
            scaler.scale(loss).backward()
            if (step + 1) % ACCUM_STEPS == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
            total_loss += loss.item()
        scheduler.step()
        print("epoch", epoch, "mean loss", total_loss / max(step, 1))
    torch.save({"model": model.state_dict(),
                "optimizer": optimizer.state_dict()}, CHECKPOINT)
    return model


def resume(model, optimizer, device):
    state = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    return model


def main(path: str = "data/tokens.npy"):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loader = token_stream(path)
    train(loader, device)


main()
