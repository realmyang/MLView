"""Shared query helpers for rules.

Keeping the loop/callee walking here is what lets a rule stay 10-40 lines.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Set, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, FunctionIR, LoopIR, ValueRef
from ..ir.provenance import DEFAULT_MAX_HOPS, Hop, extend
from ..ir.symbols import dotted_text

__all__ = [
    "within_loop", "loop_chain", "calls_in_loop", "calls_in_function",
    "with_role", "first_with_role", "arg_ref", "traced_arg", "reaches",
    "value_sources", "seed_calls", "is_seeded", "literal_of", "DATA_TAGS",
]

#: The tags a *projection* may carry across. Selecting columns out of a frame
#: does not change what the rows are; selecting a model out of a dict would be
#: an entirely different claim, so only the data tags travel this way.
DATA_TAGS = ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT",
             "TEST_SPLIT")
#: How many nested subscripts a projection is followed through.
_MAX_PROJECTION_DEPTH = 3


def literal_of(ctx, expr, scope, module) -> Optional[str]:
    """The literal a name resolves to, following one workspace import.

    `from config import NUM_WORKERS` leaves no binding in the importing module,
    so a rule that wants the *value* of `num_workers=NUM_WORKERS` has to walk
    the import table into `config.py` and read the constant there.
    """
    if expr is None:
        return None
    if isinstance(expr, ast.Constant):
        from ..ir.scopes import literal_str
        return literal_str(expr)
    name = dotted_text(expr)
    if not name:
        return None
    ref = ctx.binding_of(name, scope)
    if ref is not None and ref.literal is not None:
        return ref.literal
    symbols = getattr(module, "symbols", None)
    fqn = symbols.resolve(expr) if symbols is not None else None
    if not fqn:
        return None
    head, _dot, attr = fqn.rpartition(".")
    target = ctx.workspace.by_dotted.get(head)
    if target is None or target.module_scope is None:
        return None
    other = target.module_scope.bindings.get(attr)
    return other.literal if other is not None else None


def within_loop(loop: Optional[LoopIR], outer: LoopIR) -> bool:
    """True when `loop` is `outer` or nested inside it."""
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False


def loop_chain(loop: LoopIR) -> List[LoopIR]:
    """`loop` and every loop enclosing it, innermost first."""
    out: List[LoopIR] = []
    cur: Optional[LoopIR] = loop
    while cur is not None:
        out.append(cur)
        cur = cur.parent_loop
    return out


def calls_in_loop(ctx, loop: LoopIR, follow: bool = True) -> List[CallSite]:
    """Every call in a loop body, following one level of workspace calls."""
    out = [c for c in loop.module.calls if within_loop(c.loop, loop)]
    if follow:
        for call in list(out):
            target = ctx.follow_call(call)
            if target is not None:
                out.extend(target.calls)
    return out


def calls_in_function(ctx, func: FunctionIR, follow: bool = False) -> List[CallSite]:
    out = list(func.calls)
    if follow:
        for call in list(out):
            target = ctx.follow_call(call)
            if target is not None and target is not func:
                out.extend(target.calls)
    return out


def with_role(calls: Iterable[CallSite], *roles: str) -> List[CallSite]:
    wanted = set(roles)
    out = []
    for call in calls:
        for fqn in call.canonical_fqns or ():
            if K.role_of(fqn) in wanted:
                out.append(call)
                break
    return out


def first_with_role(calls: Iterable[CallSite], *roles: str) -> Optional[CallSite]:
    found = with_role(calls, *roles)
    found.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return found[0] if found else None


def arg_ref(ctx, call: CallSite, index: int = 0) -> Tuple[Optional[str], Optional[ValueRef]]:
    """The name and binding of a positional argument."""
    if index >= len(call.args):
        return None, None
    name = dotted_text(call.args[index])
    if not name:
        return None, None
    return name, ctx.binding_of(name, call.scope)


def traced_arg(ctx, call: CallSite, index: int = 0
               ) -> Tuple[Optional[str], Optional[ValueRef]]:
    """`arg_ref`, plus DATAFLOW-IP's one-step **projection** read.

    `self.scaler.fit_transform(frame[FEATURES])` is how a DataModule is
    written, and `dotted_text` on a `Subscript` is `None`, so the fit site had
    no traced argument at all and MLV101 recorded a coverage gap instead of the
    high-severity leak that was really there. In `--dataflow ip` the subscript
    is followed to its base and the base's data tags are read, as one recorded
    hop: the finding is de-rated once for it and names it in its evidence, so
    the reader sees that the analyzer reasoned about `frame`, not about
    `frame[FEATURES]`.

    In `--dataflow local` this is exactly `arg_ref`, byte for byte.
    """
    name, ref = arg_ref(ctx, call, index)
    if ref is not None or getattr(ctx, "dataflow", "local") != "ip":
        return name, ref
    if index >= len(call.args):
        return name, ref
    found = _projection(ctx, call, call.args[index])
    # Falling back to `arg_ref`'s own answer matters: it is what a COVERAGE
    # note names. Returning `(None, None)` on a projection that found nothing
    # turned one honest note about `X` into two - one about `X` and one about
    # "the value" - which is noise dressed as candour.
    return found if found[1] is not None else (name, ref)


def _projection(ctx, call: CallSite, arg
                ) -> Tuple[Optional[str], Optional[ValueRef]]:
    """The tracked value a subscript expression is a projection of."""
    node, depth = arg, 0
    while isinstance(node, ast.Subscript) and depth < _MAX_PROJECTION_DEPTH:
        node, depth = node.value, depth + 1
    if depth == 0:
        return None, None
    name = dotted_text(node)
    if not name:
        return None, None
    ref = ctx.binding_of(name, call.scope, at=call.loc.line)
    if ref is None or not ref.has(*DATA_TAGS):
        return None, None
    hop = Hop(kind="projection", detail="a subscript of `%s`" % name,
              loc=ref.loc or call.loc)
    chain = extend(getattr(ref, "provenance", ()) or (), hop,
                   getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    if chain is None:
        return None, None            # the cap; stay silent rather than guess
    derived = ValueRef(name=name, scope=ref.scope, tags=ref.tags,
                       producer=ref.producer, loc=ref.loc, sources=ref.sources,
                       class_ir=ref.class_ir, is_config=ref.is_config,
                       via_fqns=ref.via_fqns, provenance=chain)
    return name, derived


def value_sources(ctx, name: str, scope, depth: int = 6) -> Set[str]:
    """Every name reachable backwards through the SSA-lite chain."""
    seen: Set[str] = set()
    frontier = [name]
    while frontier and depth > 0:
        depth -= 1
        nxt: List[str] = []
        for current in frontier:
            if current in seen:
                continue
            seen.add(current)
            ref = ctx.binding_of(current, scope)
            if ref is None:
                continue
            for source in ref.sources:
                if source not in seen:
                    nxt.append(source)
        frontier = nxt
    return seen


def reaches(ctx, name: str, scope, targets: Iterable[str], depth: int = 6) -> bool:
    """Does `name` derive from any of `targets` (by value identity)?"""
    wanted = {t for t in targets if t}
    if not wanted:
        return False
    if name in wanted:
        return True
    return bool(value_sources(ctx, name, scope, depth) & wanted)


def seed_calls(ctx) -> List[CallSite]:
    """Every call that actually seeds a random source."""
    out: List[CallSite] = []
    for call in ctx.calls_with_role("SEED"):
        fqn = call.fqn or ""
        if fqn.endswith("default_rng") or fqn.endswith("RandomState"):
            if not call.args and not call.kwarg_nodes:
                continue                    # unseeded generator
        out.append(call)
    return out


def is_seeded(ctx) -> bool:
    """A seed call anywhere, or any explicit `random_state=` / `generator=`."""
    if seed_calls(ctx):
        return True
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            for key in ("random_state", "generator", "seed", "random_seed"):
                node = call.kwarg_nodes.get(key)
                if node is None:
                    continue
                if isinstance(node, ast.Constant) and node.value is None:
                    continue
                return True
    return False
