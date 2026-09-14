"""Loop *kind* classification - the pass that runs once bindings exist.

Split out of `ir/scopes.py`, which re-exports `classify_loops`.
"""

from __future__ import annotations

import ast
from typing import Dict

from .model import LoopIR, ModuleIR
from .symbols import dotted_text

__all__ = ["classify_loops"]

_LOADER_NAME_RE = ("loader", "_dl", "dl_", "batches", "dataloader")
_EPOCH_NAMES = ("epoch", "epochs", "n_epochs", "num_epochs", "max_epochs")


def _unwrap_iter(node: ast.expr) -> ast.expr:
    """Strip enumerate()/zip()/tqdm() wrappers around the iterated value."""
    seen = 0
    while isinstance(node, ast.Call) and seen < 4:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        if name in ("enumerate", "tqdm", "zip", "iter", "list", "reversed", "trange"):
            if not node.args:
                return node
            node = node.args[0]
            seen += 1
            continue
        break
    return node


def classify_loops(module: ModuleIR, binding_lookup) -> None:
    """Assign `kind`, `iterates` and a stable qualname to every loop."""
    counters: Dict[str, int] = {}
    for loop in module.loops:
        kind, evidence, value = _classify(loop, binding_lookup)
        loop.kind = kind
        loop.evidence = evidence
        loop.iterates = value
    for loop in module.loops:
        base = "%s.%s_loop" % (loop.scope.qualname, loop.kind)
        counters[base] = counters.get(base, 0) + 1
        loop.qualname = base if counters[base] == 1 else "%s%d" % (base, counters[base])


def _classify(loop: LoopIR, binding_lookup):
    node = loop.node
    if not isinstance(node, (ast.For, ast.AsyncFor)):
        return "other", (), None
    iter_node = _unwrap_iter(node.iter)
    targets = loop.targets
    value = None
    name = dotted_text(iter_node)
    if name:
        value = binding_lookup(name, loop.scope)

    # fold: iterating a splitter's .split()
    if isinstance(iter_node, ast.Call):
        callee = iter_node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "split":
            base = dotted_text(callee.value)
            base_ref = binding_lookup(base, loop.scope) if base else None
            if base_ref is not None and base_ref.producer is not None:
                from ..knowledge import role_of
                if role_of(base_ref.producer.fqn) in ("SPLITTER", "SPLIT"):
                    return "fold", ("iterates a cross-validation splitter",), base_ref
            if base and any(k in base.lower() for k in ("kfold", "splitter", "cv", "skf")):
                return "fold", ("iterates a splitter-named value",), base_ref
        func_fqn = None
        if isinstance(callee, ast.Name):
            func_fqn = callee.id
        if func_fqn == "range":
            arg_names = [dotted_text(a) or "" for a in iter_node.args]
            if any(any(e in (a or "").lower() for e in _EPOCH_NAMES) for a in arg_names):
                return "epoch", ("range() over an epoch count",), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("range() with an epoch target",), None
            # A *fully* literal range - `range(10)`, `range(0, 100, 5)`. One
            # literal bound is not enough: `range(1, len(parts))` is ordinary
            # index arithmetic, not an epoch count.
            if iter_node.args and all(isinstance(a, ast.Constant) for a in iter_node.args):
                return "epoch", ("range() over a literal count",), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("epoch loop target",), None
            return "other", (), None

    if any("epoch" in t.lower() for t in targets):
        return "epoch", ("loop target named epoch",), None

    if value is not None and value.has("LOADER"):
        return "batch", ("iterates a LOADER-tagged value",), value
    lowered = (name or "").lower()
    if lowered and any(k in lowered for k in _LOADER_NAME_RE):
        return "batch", ("iterates a loader-named value",), value
    if value is not None and value.has("TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT", "BATCH"):
        return "batch", ("iterates a split value",), value
    return "other", (), value
