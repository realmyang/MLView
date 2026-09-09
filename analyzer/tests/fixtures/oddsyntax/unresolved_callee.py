"""ANA-5a fixture: five callees the analyzer genuinely cannot resolve.

This is the shape the hostile-syntax corpus measured, reduced to one file: the
model, the criterion and the optimizer are all reached through a construct that
defeats static resolution, and before ANA-5a every one of them produced **no
node at all**, with `dynamic: 0` on everything that survived - a file MLView
could not read, reported exactly like a file MLView had read and found clean.

Each site is a different construct, and the diagnostic names each one:

* `BUILDERS[kind]()`      - a subscript
* `make_criterion()()`    - the result of another call
* `build_head()`          - a lambda-bound name
* `optimizer_cls(...)`    - a value assigned in a `match` case
* `recipe.make_head()`    - a dataclass `default_factory`
"""
from __future__ import annotations

from dataclasses import dataclass, field

import torch
import torch.nn as nn

BUILDERS = {"linear": lambda: nn.Linear(32, 8)}


def make_criterion():
    return lambda: nn.CrossEntropyLoss()


@dataclass
class Recipe:
    make_head: object = field(default_factory=lambda: nn.Identity)


def build(kind: str = "linear", lr: float = 1e-3):
    model = BUILDERS[kind]()
    criterion = make_criterion()()

    build_head = lambda: nn.Linear(8, 2)      # noqa: E731 - the point of the fixture
    head = build_head()

    match kind:
        case "linear":
            optimizer_cls = torch.optim.Adam
        case _:
            optimizer_cls = torch.optim.SGD
    optimizer = optimizer_cls(model.parameters(), lr=lr)

    recipe = Recipe()
    extra = recipe.make_head()

    return model, criterion, head, optimizer, extra
