"""`python -m tabular_trainer` and the `tabular-trainer` console script both
land here.

The `main()` below is what `pyproject.toml` points its entry point at, so this
module is the package's real entrypoint even though there is no top-level
script anywhere in the tree.
"""
from __future__ import annotations

import random
import sys

import numpy as np
import torch

from .config import TrainConfig, from_args
from .data import build_loaders
from .engine import train
from .engine.evaluator import report
from .models import CreditMLP
from .utils.io import ensure_dir, write_json
from .utils.logging import get_logger

log = get_logger(__name__)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def run(cfg: TrainConfig) -> int:
    seed_everything(cfg.seed)
    train_loader, test_loader, _ = build_loaders(cfg)
    model = CreditMLP.from_config(cfg)
    history = train(model, train_loader, test_loader, cfg)

    out = ensure_dir(cfg.out_dir)
    metrics = report(model, test_loader, torch.device(cfg.device))
    write_json(str(out / "metrics.json"), metrics)
    torch.save(model.state_dict(), str(out / "model.pt"))
    log.info("final %s", metrics)
    return 0


def main(argv=None) -> int:
    return run(from_args(argv))


if __name__ == "__main__":
    sys.exit(main())
