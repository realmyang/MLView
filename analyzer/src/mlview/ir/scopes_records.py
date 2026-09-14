"""`AssignRecord` and literal stringification.

Split out of `ir/scopes.py`, which re-exports both. The bottom of the `ir`
stack: nothing here imports a sibling, and `scopes_walk` / `bindings_store`
import it.
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
