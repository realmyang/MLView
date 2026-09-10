"""`add_argument(default=)`, keyed by dest the way argparse derives one."""
from __future__ import annotations

import argparse

from torch.utils.data import DataLoader, TensorDataset

parser = argparse.ArgumentParser()
parser.add_argument("--num-workers", type=int, default=6)
parser.add_argument("--seed", dest="random_seed", default=7)
parser.add_argument("--amp", action="store_true")
args = parser.parse_args()

loader = DataLoader(TensorDataset(), num_workers=args.num_workers)
