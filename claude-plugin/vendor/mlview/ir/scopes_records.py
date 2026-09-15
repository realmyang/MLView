"""`AssignRecord`: one binding-creating statement, as the walk recorded it.

The record is the whole contract between the structural walk
(`ir/scopes_walk.py`, which writes them in source order) and the binding pass
(`ir/bindings_store.py`, which reads them back): an assignment, `with ... as`,
`for` target, walrus or augmented assignment, with the scope, loop, function
and class it was written in, plus the two context flags a rule cannot recover
afterwards (`in_match`, `inside_no_grad`).

`literal_str` lives here for the same reason - it is the one question both
sides ask of a written-down expression, and it needs nothing else.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional, Tuple

from .model import CallSite, ClassIR, FunctionIR, Loc, LoopIR, ScopeIR

__all__ = ["AssignRecord", "literal_str"]


@dataclass
class AssignRecord:
    """One binding-creating statement, in source order."""

    kind: str                       # assign | ann | aug | for | with | walrus
    targets: Tuple[ast.expr, ...]
    value: Optional[ast.expr]
    scope: ScopeIR
    loc: Loc
    call: Optional[CallSite] = None
    stmt_index: int = 0
    loop: Optional[LoopIR] = None
    function: Optional[FunctionIR] = None
    class_ir: Optional[ClassIR] = None
    #: ANA-5a: written inside a `match` case body. Which arm ran is undecidable
    #: statically, so a name bound here is the textbook unresolvable callee.
    in_match: bool = False
    #: INFRA-01: the statement runs under `torch.no_grad()` /
    #: `inference_mode()`. `CallSite` has carried this since MLV204; an
    #: assignment needs it for the same reason - there is no autograd graph to
    #: keep alive under no_grad, so MLV205 has nothing to say about a value
    #: accumulated there.
    inside_no_grad: bool = False


def literal_str(node: Optional[ast.AST]) -> Optional[str]:
    """Stringify a literal expression; None when it is not a literal."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, str):
            return value
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return repr(value)
        return None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        parts = [literal_str(e) for e in node.elts]
        if any(p is None for p in parts):
            return None
        open_, close = ("[", "]") if isinstance(node, ast.List) else ("(", ")")
        if isinstance(node, ast.Set):
            open_, close = "{", "}"
        return open_ + ", ".join(parts) + close
    if isinstance(node, ast.Dict):
        items = []
        for k, v in zip(node.keys, node.values):
            ks, vs = literal_str(k), literal_str(v)
            if ks is None or vs is None:
                return None
            items.append("%s: %s" % (ks, vs))
        return "{" + ", ".join(items) + "}"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = literal_str(node.operand)
        return "-%s" % inner if inner is not None else None
    if isinstance(node, ast.Attribute) or isinstance(node, ast.Name):
        return None
    return None
