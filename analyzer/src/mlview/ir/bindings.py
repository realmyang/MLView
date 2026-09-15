"""Flow-insensitive binding tracking.

Every assignment, tuple unpacking, `with ... as`, `for` target, walrus and
`self.x` attribute becomes a `ValueRef` carrying the `ValueTag`s that dataflow
(never a name regex alone) established. `call_output_tags` decides what a call
hands back, including one level of in-workspace return-type inference
(`ir/returns.py`) and the pandas frame pass-through.

The other direction - `obj.m(...)` -> the canonical FQNs it answers to - lives
in `ir/resolve.py`, which imports from here.

The pass is four modules, sliced apart at the layers it already had, and this
one is the name every importer keeps using:

  * `ir/bindings_lookup.py`  name -> `ValueRef`: the store and the walk that
    reads it back at a line (`binding_of`).
  * `ir/bindings_tags.py`    what a *call* hands back: `call_output_tags` and
    the role/name tables it reasons over.
  * `ir/bindings_values.py`  what an *expression* evaluates to: value facts,
    literal containers, subscript slots, restored models.
  * `ir/bindings_store.py`   the pass itself: `bind_module` walks a module's
    assignment records and writes the bindings.
"""

from __future__ import annotations

from .bindings_lookup import binding_of, names_in  # noqa: F401
from .bindings_store import bind_module, rebind_projections  # noqa: F401
from .bindings_tags import (IDENTITY_METHODS, TENSOR_ROLES,  # noqa: F401
                            call_output_tags, identity_receiver)
#: `ir/returns.py` reads these two by their private names to answer "would
#: selecting this subscript out of a container project a split?" - they stay
#: importable from here, where that module has always found them.
from .bindings_values import _PROJECTION_TAGS, _subscript_base  # noqa: F401
#: ANA-10 moved the definition to `ir.config_values`, which is the pass that
#: acts on it, and re-exports it here so every existing importer of
#: `mlview.ir.bindings.CONFIG_NAME_RE` is unchanged and the two spellings of
#: "a config-shaped name" cannot drift apart.
from .config_values import CONFIG_NAME_RE  # noqa: F401

__all__ = ["binding_of", "bind_module", "rebind_projections",
           "call_output_tags", "names_in",
           "identity_receiver", "CONFIG_NAME_RE", "IDENTITY_METHODS", "TENSOR_ROLES"]
