"""One level of return-type inference for in-workspace functions.

    def build_optimizer(model, cfg):
        if cfg["name"] == "adam":
            return optim.Adam(model.parameters(), lr=cfg["lr"])
        return optim.SGD(model.parameters(), lr=cfg["lr"])

    opt = build_optimizer(model, cfg)   # <- without this pass, untyped

A factory like that is present in a large fraction of real training repos, and
without it `opt` carries no tags, `opt.step()` resolves to nothing, and every
absence rule in the train-loop family (MLV201 / MLV202) fires on correct code.
The same hole makes `model = build_model(cfg).to(device)` invisible to MLV501.

The pass is deliberately shallow and conservative:

* only the callee's own `return` expressions are read, one level deep;
* branches are **merged**: FQNs are unioned (so `Adam` or `SGD` both resolve to
  the optimizer family), tags are **intersected** across the branches that have
  any (so `X_train if train else X_test` cannot invent a TRAIN_SPLIT), and the
  workspace class is kept only when every branch agrees on it;
* `return a, b` propagates per position, which is what
  `opt, sched = build(model, epochs)` needs.

Recursion is guarded by an `active` set, so a self-calling factory yields no
summary rather than looping.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .model import ClassIR, FunctionIR, sort_tags
from .symbols import dotted_text

__all__ = ["ReturnSlot", "ReturnSummary", "infer_returns", "slot_of"]

#: Never propagate more than this many candidate FQNs from one function.
_MAX_FQNS = 6
#: A tuple return wider than this is not worth tracking positionally.
_MAX_POSITIONS = 8
#: How many nested workspace calls one `return` expression may be followed
#: through. Two is what this pass has always done; DATAFLOW-IP raises it to the
#: interprocedural hop cap and iterates to the fixed point.
_DEFAULT_DEPTH = 2


@dataclass(frozen=True)
class ReturnSlot:
    """What one returned position is statically known to be."""

    fqns: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    class_ir: Optional[ClassIR] = None
    #: GRAPH-R3. The noun phrase for the construct that defeated the analyzer
    #: when the return could not be typed **at all** - "a subscript", "a
    #: lambda", "a dataclass default_factory". A registry factory
    #: (`return _REGISTRY[group][name](**kwargs)`) is the canonical case, and it
    #: is present in a large fraction of research repositories. Appended last
    #: and defaulted, so a slot that names a symbol is exactly what it was:
    #: this field is set only when `fqns`, `tags` and `class_ir` are all empty,
    #: and it asserts nothing about what the value *is* - only that the analyzer
    #: knows it could not follow it, which is what lets `core/workspace_ops`
    #: draw an honest `unknown` box instead of nothing at all.
    opaque: Optional[str] = None
    #: REC-04. The dict / list / tuple **literal** the function returns, with
    #: the scope and module its element expressions must be read in. GRAPH-R3
    #: resolves an object out of a container only where the literal is assigned
    #: to a name in the same scope, so a `make_state()` factory - which is how
    #: the shape is actually written - lost everything inside it at the
    #: `return`. Carried exactly one level, like every other slot field.
    container: Optional[Any] = None
    container_scope: Optional[Any] = None
    container_module: Optional[Any] = None

    def __bool__(self) -> bool:
        return bool(self.fqns or self.tags or self.class_ir is not None
                    or self.opaque or self.container is not None)


@dataclass(frozen=True)
class ReturnSummary:
    """The scalar return of a function, plus its tuple positions."""

    scalar: Optional[ReturnSlot] = None
    positions: Tuple[Optional[ReturnSlot], ...] = ()


def slot_of(call, index: Optional[int] = None) -> Optional[ReturnSlot]:
    """The `ReturnSlot` a call site yields, for a scalar or a tuple position."""
    func = getattr(call, "target_function", None) if call is not None else None
    summary = getattr(func, "return_summary", None) if func is not None else None
    if summary is None:
        return None
    if index is None:
        return summary.scalar
    if 0 <= index < len(summary.positions):
        return summary.positions[index]
    return None


def infer_returns(workspace, max_depth: int = _DEFAULT_DEPTH) -> None:
    """(Re)compute `FunctionIR.return_summary` for every workspace function.

    `max_depth` is DATAFLOW-IP's RETURN summary: `local` keeps the two levels
    this pass has always walked, and `ip` raises it to the hop cap and runs the
    whole pass again until the summaries stop moving (`ir.summaries`), so a tag
    flows out through a chain of helpers rather than one of them. The default
    reproduces today's inference exactly.
    """
    memo: Dict[int, Optional[ReturnSummary]] = {}
    active: Set[int] = set()
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            func.return_summary = _summary(func, workspace, memo, active, 0,
                                           max_depth)


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------

def _summary(func: FunctionIR, workspace, memo, active, depth: int,
             max_depth: int = _DEFAULT_DEPTH) -> Optional[ReturnSummary]:
    key = id(func)
    if key in memo:
        return memo[key]
    if key in active or depth > max_depth or not func.returns:
        return None
    active.add(key)
    try:
        scalars: List[ReturnSlot] = []
        positions: Dict[int, List[ReturnSlot]] = {}
        arity: Optional[int] = None
        for expr in func.returns:
            if isinstance(expr, (ast.Tuple, ast.List)):
                width = len(expr.elts)
                if arity is None:
                    arity = width if width <= _MAX_POSITIONS else -1
                if arity != width:
                    arity = -1            # branches disagree: drop the positions
                    continue
                for index, elt in enumerate(expr.elts):
                    slot = _slot(elt, func, workspace, memo, active, depth, max_depth)
                    if slot:
                        positions.setdefault(index, []).append(slot)
                continue
            slot = _slot(expr, func, workspace, memo, active, depth, max_depth)
            if slot:
                scalars.append(slot)
        summary = ReturnSummary(
            scalar=_merge(scalars),
            positions=tuple(_merge(positions.get(i, ())) for i in range(arity))
            if arity and arity > 0 else ())
        if summary.scalar is None and not any(summary.positions):
            summary = None
    finally:
        active.discard(key)
    memo[key] = summary
    return summary


def _slot(expr, func: FunctionIR, workspace, memo, active, depth: int,
          max_depth: int = _DEFAULT_DEPTH) -> Optional[ReturnSlot]:
    """What one `return <expr>` yields, statically."""
    from .bindings import binding_of, call_output_tags   # local: cyclic at import

    if expr is None:
        return None
    module = func.module
    if isinstance(expr, (ast.Dict, ast.List, ast.Tuple)):
        # REC-04: `return {"scaler": GradScaler(...), "model": model}`. The
        # literal itself is the answer; its elements are read later, in the
        # scope that wrote them.
        return ReturnSlot(container=expr, container_scope=func.scope,
                          container_module=module)
    if isinstance(expr, ast.Call):
        call = getattr(module, "_calls_by_node", {}).get(id(expr))
        if call is None:
            return None
        inner = call.target_function
        if inner is not None and inner is not func:
            nested = _summary(inner, workspace, memo, active, depth + 1, max_depth)
            return nested.scalar if nested is not None else None
        slot = ReturnSlot(fqns=_trim(call.canonical_fqns),
                          tags=tuple(call_output_tags(call, call.scope)),
                          class_ir=call.class_ir,
                          opaque=call.unresolved_callee)
        return slot or None
    name = dotted_text(expr)
    if not name:
        return None
    ref = binding_of(name, func.scope)
    if ref is None:
        return None
    fqns = tuple(ref.via_fqns)
    if not fqns and ref.producer is not None:
        fqns = _trim(ref.producer.canonical_fqns
                     or ((ref.producer.fqn,) if ref.producer.fqn else ()))
    slot = ReturnSlot(fqns=fqns, tags=tuple(ref.tags), class_ir=ref.class_ir,
                      opaque=ref.opaque, container=ref.container,
                      container_scope=(ref.container_scope or func.scope)
                      if ref.container is not None else None,
                      container_module=(ref.container_module or module)
                      if ref.container is not None else None)
    return slot or None


def _trim(fqns: Sequence[str]) -> Tuple[str, ...]:
    return tuple(f for f in (fqns or ()) if f)[:_MAX_FQNS]


def _merge(slots: Sequence[ReturnSlot]) -> Optional[ReturnSlot]:
    """Union the FQNs, intersect the tags, keep a class only if all agree."""
    kept = [s for s in slots if s]
    if not kept:
        return None
    fqns: List[str] = []
    for slot in kept:
        for fqn in slot.fqns:
            if fqn not in fqns:
                fqns.append(fqn)

    tagged = [set(s.tags) for s in kept if s.tags]
    tags: Set[str] = set()
    if tagged:
        tags = set(tagged[0])
        for other in tagged[1:]:
            tags &= other

    classes = {id(s.class_ir): s.class_ir for s in kept if s.class_ir is not None}
    class_ir = list(classes.values())[0] if len(classes) == 1 else None

    # Opacity is the *last* answer, never a competing one: a branch that names a
    # symbol tells the reader more than a branch that named nothing, so the
    # merged slot is opaque only when no branch typed anything.
    opaque = None
    if not fqns and not tags and class_ir is None:
        for slot in kept:
            if slot.opaque:
                opaque = slot.opaque
                break

    # A container survives the merge only when every branch returned the very
    # same literal; two different dicts are not one container.
    containers = {id(s.container): s for s in kept if s.container is not None}
    holder = (list(containers.values())[0]
              if len(containers) == 1 and len(containers) == len(kept) else None)

    slot = ReturnSlot(fqns=tuple(fqns[:_MAX_FQNS]), tags=sort_tags(tags),
                      class_ir=class_ir, opaque=opaque,
                      container=holder.container if holder is not None else None,
                      container_scope=holder.container_scope if holder is not None
                      else None,
                      container_module=holder.container_module if holder is not None
                      else None)
    return slot or None
