"""DATAFLOW-IP probe: the RETURN summary, run to its fixed point.

`ir/returns.py` walked two levels of nested workspace calls and stopped, which
is one level short of the delegation chain a config-driven repo actually
writes: `build -> for_config -> for_name -> make` is four `def`s and one
`AdamW`. In `--dataflow local` the optimizer type is lost somewhere in the
middle and `opt` comes back untagged, so every absence rule in the train-loop
family reasons about a value it cannot see. In `--dataflow ip` the pass runs to
its fixed point, capped at `DEFAULT_MAX_HOPS`, and `opt` is an OPTIMIZER.

Nothing here is a defect, so nothing must fire in either mode.

# MLVIEW-EXPECT-NONE: MLV201, MLV202, MLV203
"""
from __future__ import annotations

import torch.optim as optim


def make(model, lr):
    return optim.AdamW(model.parameters(), lr=lr)


def for_name(model, lr, name="adamw"):
    return make(model, lr)


def for_config(model, cfg):
    return for_name(model, cfg["lr"], cfg["optimizer"])


def build(model, cfg):
    return for_config(model, cfg)
