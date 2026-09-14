"""ROB-21. The package whose *parent* MLView walks.

`workspace/` is deliberately NOT a package (no `__init__.py`), so
`core/coverage._package_root()` climbs out of `pkg/` and stops here -- and
`single_file_diagnostic` then runs a second `discover()` rooted at
`workspace/`, which is outside the directory the caller asked about.
"""
from .train import train

__all__ = ["train"]
