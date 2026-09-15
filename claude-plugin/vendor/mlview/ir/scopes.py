"""Scope, loop and call-site recovery.

One walk over the AST produces: the scope tree (module / class / function),
every call site with its context flags, every loop with what it iterates,
the `with`-block gradient contexts, and the dynamic-scope markers.

Loop *kind* classification happens afterwards (`classify_loops`) because it
needs the binding table.

Three modules, and this one is the name every importer keeps using:

  * `ir/scopes_records.py`  `AssignRecord`, the one thing the walk hands the
    binding pass, and `literal_str`.
  * `ir/scopes_walk.py`     the walk itself (`walk_module`, `_Walker`).
  * `ir/scopes_loops.py`    `classify_loops`, the pass that runs after the
    bindings exist.
"""

from __future__ import annotations

from .scopes_loops import classify_loops  # noqa: F401
from .scopes_records import AssignRecord, literal_str  # noqa: F401
from .scopes_walk import callee_construct, walk_module  # noqa: F401

__all__ = ["AssignRecord", "walk_module", "classify_loops", "literal_str",
           "callee_construct"]
