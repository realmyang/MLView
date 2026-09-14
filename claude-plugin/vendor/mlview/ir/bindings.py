"""Flow-insensitive binding tracking.

Every assignment, tuple unpacking, `with ... as`, `for` target, walrus and
`self.x` attribute becomes a `ValueRef` carrying the `ValueTag`s that dataflow
(never a name regex alone) established. `call_output_tags` decides what a call
hands back, including one level of in-workspace return-type inference
(`ir/returns.py`) and the pandas frame pass-through.

The other direction - `obj.m(...)` -> the canonical FQNs it answers to - lives
in `ir/resolve.py`, which imports from here.
"""

from __future__ import annotations

from .bindings_lookup import binding_of, names_in
from .bindings_store import bind_module
from .bindings_tags import (IDENTITY_METHODS, TENSOR_ROLES, call_output_tags,
                            identity_receiver)
from .config_values import CONFIG_NAME_RE

__all__ = ["binding_of", "bind_module", "call_output_tags", "names_in",
           "identity_receiver", "CONFIG_NAME_RE", "IDENTITY_METHODS", "TENSOR_ROLES"]

#: ANA-10 moved the definition to `ir.config_values`, which is the pass that
#: acts on it, and re-exports it here so every existing importer of
#: `mlview.ir.bindings.CONFIG_NAME_RE` is unchanged and the two spellings of
#: "a config-shaped name" cannot drift apart.
