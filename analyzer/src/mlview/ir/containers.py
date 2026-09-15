"""Objects carried in a dict, a tuple or a list (GRAPH-R3).

A training script hands its objects around in a container at least as often as
it hands them around by name:

    ctx = {"scaler": GradScaler("cuda"), "model": model}
    scaler = ctx["scaler"]              # <- the GradScaler identity
    opt_a, opt_b = optimizers           # <- `optimizers = (make_a(), make_b())`

`ir/bindings_store` already records `x = f(...)` and `a, b = f(...)`; neither
line above has a call on its right-hand side, so both bound a value with no
tags, no producer and no class - and `scaler.scale(loss)`, `scaler.step(opt)`
and `opt_a.step()` then resolved to **nothing at all**: no node, no edge, no
rule. The GradScaler case is the one ROADMAP GRAPH-R3 names, and it is the
shape `torch.amp` documentation itself encourages.

What this module does is deliberately literal-only: a container is followed
**only** when the analyzer can see the literal that built it, in the same
module, and only one level. There is no aliasing analysis and no attempt to
model a container that is mutated afterwards - a `ctx["scaler"] = other` later
in the file leaves the first answer standing, which is why the value that comes
back is the *constructed* one and nothing here ever mints an FQN of its own.
"""

from __future__ import annotations

import ast
from typing import Any, Optional

from .model import ModuleIR, ScopeIR, ValueRef
from .symbols import dotted_text

__all__ = ["is_container", "element_expr", "subscript_key", "expr_value"]

#: A container literal worth remembering on the `ValueRef` that binds it.
_CONTAINERS = (ast.Dict, ast.Tuple, ast.List)


def is_container(node: Optional[ast.AST]) -> bool:
    return isinstance(node, _CONTAINERS)


def subscript_key(node: ast.Subscript) -> Any:
    """The constant key of `ctx["scaler"]` / `pair[0]`, or None."""
    index = node.slice
    if isinstance(index, ast.Constant) and isinstance(index.value, (str, int)):
        return index.value
    return None


def element_expr(container: Optional[ast.AST], key: Any) -> Optional[ast.expr]:
    """The element expression a constant key selects out of a literal."""
    if key is None or container is None:
        return None
    if isinstance(container, ast.Dict) and isinstance(key, str):
        for k, v in zip(container.keys, container.values):
            if isinstance(k, ast.Constant) and k.value == key:
                return v
        return None
    if isinstance(container, (ast.Tuple, ast.List)) and isinstance(key, int):
        if isinstance(key, bool):            # `d[True]` is not `d[1]` here
            return None
        if -len(container.elts) <= key < len(container.elts):
            return container.elts[key]
    return None


def expr_value(expr: Optional[ast.expr], scope: ScopeIR,
               module: Optional[ModuleIR], at: Optional[int] = None
               ) -> Optional[ValueRef]:
    """The `ValueRef` one element expression stands for - a name or a call.

    The two forms a container element takes in practice: `{"model": model}`
    (a name already bound) and `{"scaler": GradScaler("cuda")}` (constructed in
    place). Anything else returns None rather than a guess.
    """
    from .bindings import binding_of, call_output_tags   # local: cyclic at import
    from .returns import slot_of

    if expr is None:
        return None
    if isinstance(expr, ast.Call):
        inner = getattr(module, "_calls_by_node", {}).get(id(expr)) if module else None
        if inner is None:
            return None
        ref = ValueRef(name=inner.var or inner.short_name, scope=scope,
                       tags=call_output_tags(inner, scope), producer=inner,
                       loc=inner.loc, class_ir=inner.class_ir)
        slot = slot_of(inner)
        if slot is not None:
            ref.via_fqns = slot.fqns
            ref.class_ir = ref.class_ir or slot.class_ir
        return ref
    name = dotted_text(expr)
    return binding_of(name, scope, at=at) if name else None
