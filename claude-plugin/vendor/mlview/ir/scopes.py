"""Scope, loop and call-site recovery.

One walk over the AST produces: the scope tree (module / class / function),
every call site with its context flags, every loop with what it iterates,
the `with`-block gradient contexts, and the dynamic-scope markers.

Loop *kind* classification happens afterwards (`classify_loops`) because it
needs the binding table.
"""

from __future__ import annotations

from .scopes_loops import classify_loops
from .scopes_records import AssignRecord, literal_str
from .scopes_walk import callee_construct, walk_module

__all__ = ["AssignRecord", "walk_module", "classify_loops", "literal_str",
           "callee_construct"]
