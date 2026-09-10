"""ANA-10's probe ladder, in one file.

The roadmap measured all four rungs: `num_workers=4` fires MLV112, a module
constant fires, and the two config reads were **silent**. All four fire now,
and the two that came out of a container are de-rated so neither can be
`certain` - a wrong read must never mint a certain finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from torch.utils.data import DataLoader, TensorDataset

from conf import WORKERS

CFG = {"workers": 3, "eval": {"workers": 1}}


@dataclass
class DataCfg:
    workers: int = 2
    batch_size: int = 64


@dataclass
class Cfg:
    data: DataCfg = field(default_factory=DataCfg)
    epochs: int = 10


cfg = Cfg()
ds = TensorDataset()

rung1 = DataLoader(ds, num_workers=4)
rung2 = DataLoader(ds, num_workers=WORKERS)
rung3 = DataLoader(ds, num_workers=CFG["workers"])
rung4 = DataLoader(ds, num_workers=cfg.data.workers)
