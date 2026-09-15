"""Run configuration for the ImageNet-style classifier.

Everything a run needs is a literal here or an environment override, so the
analyzer can resolve `CFG.workers` the way it resolves `4`.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

import numpy as np
import torch

SEED = 1234
DATA_ROOT = os.environ.get("IMAGENET_ROOT", "data/imagenet")
CHECKPOINT_DIR = os.environ.get("CKPT_DIR", "checkpoints")


@dataclass
class TrainConfig:
    """One place for every knob the entrypoint reads."""

    epochs: int = 90
    batch_size: int = 256
    eval_batch_size: int = 512
    workers: int = 8
    base_lr: float = 0.1
    weight_decay: float = 5e-5
    label_smoothing: float = 0.1
    warmup_epochs: int = 5
    accum_steps: int = 4
    clip_norm: float = 1.0
    ema_decay: float = 0.9998
    image_size: int = 224
    crop_pct: float = 0.875
    channels: tuple = field(default_factory=lambda: (0.485, 0.456, 0.406))
    channel_std: tuple = field(default_factory=lambda: (0.229, 0.224, 0.225))


CFG = TrainConfig()


def set_seed(seed: int = SEED) -> None:
    """Seed every source of randomness this project touches."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device(local_rank: int = 0) -> torch.device:
    """A device that exists: CUDA when the driver says so, CPU otherwise."""
    if torch.cuda.is_available():
        return torch.device("cuda", local_rank)
    return torch.device("cpu")


def checkpoint_path(tag: str) -> str:
    return os.path.join(CHECKPOINT_DIR, "%s.pt" % tag)
