"""A name -> factory registry, the shape every research repo grows.

Everything downstream is constructed through `build()`, so the callee is only
knowable by reading the decorator calls at import time.
"""
from __future__ import annotations

from typing import Callable, Dict

_REGISTRY: Dict[str, Dict[str, Callable]] = {}


def register(group: str, name: str):
    def decorate(factory):
        _REGISTRY.setdefault(group, {})[name] = factory
        return factory
    return decorate


def build(group: str, name: str, **kwargs):
    return _REGISTRY[group][name](**kwargs)


def build_from_cfg(group: str, cfg):
    return build(group, cfg["name"], **cfg.get("args", {}))
