"""The second package `__init__`: one module, two re-exported symbols."""
from .net import Net, build_optimizer

__all__ = ["Net", "build_optimizer"]
