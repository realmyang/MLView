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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
    #: REC-04. The per-slot values of a **container literal** the function hands
    #: back: `return {"model": model, "scaler": GradScaler(...)}` and
    #: `return opt_a, opt_b`. `ir/bindings_values` already resolves a literal's
    #: slots where it is written, and `ValueRef.elements` / `.entries` carry
    #: them; what R3 shipped could not get them *out* of the function, so a
    #: `make_state()` factory - which is how the shape is actually written -
    #: lost every object inside it at the `return`. The refs are resolved in the
    #: **callee's** scope before they travel, which is why nothing here needs to
    #: re-read a name in a scope it does not belong to.
    elements: Tuple[Optional[Any], ...] = ()
    entries: Tuple[Tuple[str, Any], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.fqns or self.tags or self.class_ir is not None
                    or self.opaque or self.elements or self.entries)


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
        # slots are resolved here, in the scope that wrote them, and travel as
        # values - never as an AST the caller would have to re-read.
        from .bindings_values import _literal_elements, _literal_entries
        slot = ReturnSlot(elements=_literal_elements(expr, func.scope, module),
                          entries=_literal_entries(expr, func.scope, module))
        return slot or None
    # DGRG-02. `return a + b`, `return 0.7 * soft + 0.3 * hard` and
    # `return -critic(x).mean()` all fell straight through to `None`, so the
    # value a distillation / PPO / multi-task / VAE / contrastive helper
    # returns carried no `torch.Tensor` family, `loss.backward()` on it never
    # earned the BACKWARD role, and MLV201/202/203/205 all went silent on a
    # loop that genuinely never zeroes its gradients. A sum of two losses is a
    # loss, so the operands are recursed into and merged.
    if isinstance(expr, (ast.BinOp, ast.UnaryOp)):
        operands = [expr.operand] if isinstance(expr, ast.UnaryOp) \
            else [expr.left, expr.right]
        slots = [_slot(o, func, workspace, memo, active, depth, max_depth)
                 for o in operands]
        kept = [s for s in slots if s]
        if not kept:
            return None
        # `_merge` intersects tags, which is right for two branches of one
        # return but wrong here: `0.7 * loss` has a literal on one side, and a
        # literal contributes no tags at all. The union is what "this value is
        # built out of a loss" means.
        fqns: List[str] = []
        tags: Set[str] = set()
        for slot in kept:
            for fqn in slot.fqns:
                if fqn not in fqns:
                    fqns.append(fqn)
            tags |= set(slot.tags)
        classes = {id(s.class_ir): s.class_ir for s in kept if s.class_ir is not None}
        merged = ReturnSlot(fqns=tuple(fqns[:_MAX_FQNS]), tags=sort_tags(tags),
                            class_ir=list(classes.values())[0]
                            if len(classes) == 1 else None)
        return merged or None
    if isinstance(expr, ast.Subscript):
        # NLP2-04. `def read_shards(files): return load_dataset(...)["train"]`
        # is how every non-notebook HuggingFace project writes the first hop,
        # and a Subscript fell straight through to `None`: the caller's binding
        # was untyped, `documents.train_test_split(...)` resolved to nothing,
        # and the SPLIT node, MLV602 and the two `.map` transform nodes all
        # disappeared with an empty `diagnostics` list - on a diagram whose
        # whole purpose is "where does data enter and where is it split".
        # Round 1 fixed the same-scope form in `ir/bindings`; this is the
        # cross-function form, and it carries exactly the same tags
        # (`bindings._PROJECTION_TAGS`), because selecting a split out of a
        # `DatasetDict` does not change what the rows are.
        from .bindings import _PROJECTION_TAGS, _subscript_base
        base_ref, base_call = _subscript_base(expr, func.scope, module)
        tags: List[str] = []
        fqns: Tuple[str, ...] = ()
        class_ir = None
        if base_call is not None:
            tags = [t for t in call_output_tags(base_call, base_call.scope)
                    if t in _PROJECTION_TAGS]
            fqns = _trim(base_call.canonical_fqns)
            class_ir = base_call.class_ir
        elif base_ref is not None:
            tags = [t for t in base_ref.tags if t in _PROJECTION_TAGS]
            fqns = base_ref.via_fqns or (
                _trim(base_ref.producer.canonical_fqns)
                if base_ref.producer is not None else ())
            class_ir = base_ref.class_ir
        slot = ReturnSlot(fqns=_trim(fqns), tags=sort_tags(tags), class_ir=class_ir)
        return slot or None
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
                      opaque=ref.opaque, elements=ref.elements,
                      entries=ref.entries)
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

    # A container survives the merge only when exactly one branch carried one:
    # two different dicts are not one container, and guessing between them would
    # make `state["model"]` stand for an object no caller ever returned.
    holders = [s for s in kept if s.elements or s.entries]
    holder = holders[0] if len(holders) == 1 else None

    slot = ReturnSlot(fqns=tuple(fqns[:_MAX_FQNS]), tags=sort_tags(tags),
                      class_ir=class_ir, opaque=opaque,
                      elements=holder.elements if holder is not None else (),
                      entries=holder.entries if holder is not None else ())
    return slot or None
