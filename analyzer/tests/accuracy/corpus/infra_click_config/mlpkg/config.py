"""The configuration object: a dataclass with defaults, overlaid from TOML.

Every hyper-parameter in this project has three possible origins, in order of
precedence: a `click` option on the command line, a key in `config.toml`, and
the dataclass field default below. Two of the defaults are defects and they are
defects *because of what the default is*, not because of anything a call site
spells out:

* `shuffle: bool = False` — `training.py` passes it straight to the training
  `DataLoader`, so the default run trains on the rows in file order;
* `num_workers: int = 8` — worker processes are spawned on macOS and Windows,
  and this package's only entrypoint is a console script with no
  `if __name__ == "__main__":` guard.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict


@dataclass
class TrainConfig:
    data_root: str = "data/processed"
    epochs: int = 20
    batch_size: int = 64
    lr: float = 0.0003
    weight_decay: float = 0.01
    width: int = 192
    dropout: float = 0.15
    features: int = 40
    classes: int = 5
    seed: int = 4096
    shuffle: bool = False
    num_workers: int = 8
    out_dir: str = "checkpoints/click"


def load_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as handle:
        document = tomllib.load(handle)
    return document.get("train", {})


def build_config(path: Path, overrides: Dict[str, Any]) -> TrainConfig:
    """TOML under the dataclass defaults, CLI options over both."""
    known = {field.name for field in fields(TrainConfig)}
    settings: Dict[str, Any] = {}
    settings.update({k: v for k, v in load_toml(path).items() if k in known})
    settings.update({k: v for k, v in overrides.items()
                     if k in known and v is not None})
    return TrainConfig(**settings)
