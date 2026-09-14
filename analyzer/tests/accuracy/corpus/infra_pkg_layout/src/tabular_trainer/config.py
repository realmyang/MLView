"""One dataclass, one argparse parser, one `from_args` bridge.

This is the whole configuration surface of the package: every module below
takes a `TrainConfig` and reads attributes off it, so the analyzer has to
follow a dataclass field default to know what `cfg.batch_size` is.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import List


@dataclass
class TrainConfig:
    csv_path: str = "data/credit.csv"
    target: str = "default"
    features: List[str] = field(default_factory=lambda: [
        "limit", "age", "bill_1", "bill_2", "pay_1", "pay_2"])
    batch_size: int = 256
    num_workers: int = 4
    epochs: int = 30
    lr: float = 1e-3
    weight_decay: float = 1e-4
    hidden: int = 256
    dropout: float = 0.2
    test_size: float = 0.2
    seed: int = 1234
    device: str = "cpu"
    out_dir: str = "artifacts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tabular-trainer",
        description="Train the credit-default classifier.")
    parser.add_argument("--csv-path", default="data/credit.csv")
    parser.add_argument("--target", default="default")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--hidden", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out-dir", default="artifacts")
    return parser


def from_args(argv=None) -> TrainConfig:
    args = build_parser().parse_args(argv)
    return TrainConfig(
        csv_path=args.csv_path,
        target=args.target,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        epochs=args.epochs,
        lr=args.lr,
        weight_decay=args.weight_decay,
        hidden=args.hidden,
        dropout=args.dropout,
        test_size=args.test_size,
        seed=args.seed,
        device=args.device,
        out_dir=args.out_dir,
    )
