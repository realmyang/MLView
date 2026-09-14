"""A decorator registry — the detectron2 / mmdet / timm / fairseq idiom.

`@MODELS.register("wide_resnet")` puts a class in a dict at import time and
`MODELS.build(cfg)` takes it back out by a string that came from a config file.
Nothing about the mapping is visible at the call site: the name is a `str`, the
lookup is a subscript, and the class is only reachable by reading the decorator.

This module is deliberately tiny and framework-free so the shape can be judged
on its own. `plugins.py` is where the classes are registered, and `train.py` is
where `build` is called.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, TypeVar

T = TypeVar("T")


class Registry:
    """A name -> factory table with a decorator front door."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._table: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str) -> Callable[[T], T]:
        def decorate(factory: T) -> T:
            if name in self._table:
                raise KeyError("%s %r is already registered" % (self.kind, name))
            self._table[name] = factory  # type: ignore[assignment]
            return factory
        return decorate

    def get(self, name: str) -> Callable[..., Any]:
        if name not in self._table:
            raise KeyError("unknown %s %r; known: %s"
                           % (self.kind, name, sorted(self._table)))
        return self._table[name]

    def build(self, config: Mapping[str, Any]) -> Any:
        settings = dict(config)
        name = settings.pop("name")
        return self.get(name)(**settings)

    def names(self):
        return sorted(self._table)


MODELS = Registry("model")
LOSSES = Registry("loss")
OPTIMIZERS = Registry("optimizer")
