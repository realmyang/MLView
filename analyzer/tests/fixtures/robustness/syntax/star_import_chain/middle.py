
from base import *  # noqa: F401,F403

__all__ = ["build_model", "CRIT", "make_loader", "OPT"]

import torch

OPT = torch.optim.Adam
