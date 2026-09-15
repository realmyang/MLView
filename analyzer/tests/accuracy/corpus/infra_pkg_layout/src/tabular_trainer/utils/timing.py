"""A context-manager stopwatch. No ML anywhere in this module."""
from __future__ import annotations

import time
from typing import Optional


class Stopwatch:
    def __init__(self, label: str = "block") -> None:
        self.label = label
        self.started: Optional[float] = None
        self.elapsed = 0.0

    def __enter__(self) -> "Stopwatch":
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.started is not None:
            self.elapsed = time.perf_counter() - self.started
        return False

    def __str__(self) -> str:
        return "%s took %.3fs" % (self.label, self.elapsed)
