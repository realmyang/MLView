"""The train and evaluate passes (defective twin).

Defect 6: nothing ever zeroes the gradients, so every optimiser step applies
the running sum of the whole epoch.
Defect 7: the epoch loss is accumulated as a live tensor.
Defect 8: `evaluate()` never switches to eval mode and never disables grad, so
dropout fires and the BatchNorm running statistics keep moving while the
validation set is scored.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn
from torch.amp import GradScaler, autocast

from config import CFG, checkpoint_path
from data import move_batch


def build_optimizer(model: nn.Module, lr: float = CFG.base_lr):
    """Decay on weights, no decay on norms and biases."""
    decay, no_decay = [], []
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        if parameter.ndim <= 1 or name.endswith(".bias"):
            no_decay.append(parameter)
        else:
            decay.append(parameter)
    groups = [
        {"params": decay, "weight_decay": CFG.weight_decay},
        {"params": no_decay, "weight_decay": 0.0},
    ]
    return torch.optim.SGD(groups, lr=lr, momentum=0.9, nesterov=True)


def build_scheduler(optimizer, steps_per_epoch: int):
    """One cycle over the whole run - it has to be stepped per batch."""
    total_steps = max(1, steps_per_epoch * CFG.epochs)
    return torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=CFG.base_lr,
        total_steps=total_steps,
        pct_start=CFG.warmup_epochs / max(CFG.epochs, 1),
        anneal_strategy="cos",
    )


def accuracy_topk(logits: torch.Tensor, targets: torch.Tensor, k: int = 5):
    """Top-1 and top-k hit counts from ranked class indices."""
    ranked = logits.topk(k, dim=1).indices
    top1 = (ranked[:, 0] == targets).sum().item()
    topk = (ranked == targets.unsqueeze(1)).any(dim=1).sum().item()
    return top1, topk


def train_one_epoch(model, ema, loader, criterion, optimizer, scaler, scheduler,
                    device, epoch: int):
    """One epoch - with no zero_grad and a tensor-valued running loss."""
    model.train()
    running_loss = 0.0
    seen = 0

    for step, batch in enumerate(loader):
        images, targets = move_batch(batch, device)
        with autocast(device_type=device.type, dtype=torch.float16):
            logits = model(images)
            loss = criterion(logits, targets) / CFG.accum_steps

        scaler.scale(loss).backward()

        if (step + 1) % CFG.accum_steps == 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), CFG.clip_norm)
            scaler.step(optimizer)
            scaler.update()
            ema.update(model)

        running_loss += loss
        seen += targets.size(0)
        if step % 100 == 0:
            print("epoch %d step %d loss %.4f" % (epoch, step, float(loss)))

    return running_loss / max(seen, 1)


def evaluate(model, loader, criterion, device) -> dict:
    """Defect 8: no model.eval(), no torch.no_grad()."""
    total_loss = 0.0
    top1 = 0
    top5 = 0
    seen = 0
    for batch in loader:
        images, targets = move_batch(batch, device)
        logits = model(images)
        loss = criterion(logits, targets)
        hit1, hit5 = accuracy_topk(logits, targets, k=5)
        total_loss += loss.item() * targets.size(0)
        top1 += hit1
        top5 += hit5
        seen += targets.size(0)
    return {
        "loss": total_loss / max(seen, 1),
        "top1": top1 / max(seen, 1),
        "top5": top5 / max(seen, 1),
    }


def save_checkpoint(model, ema, optimizer, scaler, epoch: int, best: float,
                    tag: str = "last") -> str:
    """Defect 9: the whole module is pickled, not its state dict."""
    path = checkpoint_path(tag)
    torch.save(model, path)
    return path


def load_checkpoint(path: str, model, device):
    """Defect 9, the other half: an unrestricted torch.load."""
    payload = torch.load(path)
    return payload


def make_scaler(device: torch.device) -> GradScaler:
    return GradScaler(device.type)


def cosine_warmup_factor(step: int, warmup_steps: int, total_steps: int) -> float:
    """The schedule OneCycleLR implements, kept here for the run log."""
    if step < warmup_steps:
        return step / max(warmup_steps, 1)
    progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
    return 0.5 * (1.0 + math.cos(math.pi * progress))
