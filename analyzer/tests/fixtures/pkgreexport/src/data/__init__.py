"""ANA-3: a package `__init__` re-exporting the module beside it.

`_relative_base` used to drop this module's last dotted component even though
`src/data/__init__.py` is already named `src.data`, so `from .windows import
WindowDataset` resolved to `src.windows` - a module that does not exist. The
class was then drawn as an orphan and the importer got a `dynamic_scope` note.
"""
from .windows import WindowDataset

__all__ = ["WindowDataset"]
