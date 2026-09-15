"""Name -> `ValueRef` lookup: the read side of the binding store.

Split out of `ir/bindings.py`, which re-exports everything here. Nothing in
this module imports its siblings - `bindings_tags` and `bindings_store` import
*it*, in that order.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Sequence, Tuple

from .model import CallSite, ScopeIR, ValueRef
from .symbols import dotted_text

__all__ = ["binding_of", "names_in"]


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def binding_of(name: Optional[str], scope: Optional[ScopeIR],
               at: Optional[int] = None, in_loop: bool = False,
               exclude: Optional[CallSite] = None) -> Optional[ValueRef]:
    """The `ValueRef` a name resolves to, walking the scope chain outwards.

    With `at` (the 1-based line of the *consumer*) the name is resolved against
    the store in effect at that line rather than against the last store in the
    scope - REV-01. `bindings` is a flat `name -> one ValueRef` map, so a
    rebound name kept only its last producer, and `x = self.pool(x)` at line 42
    was handed to the consumer `self.stem(x)` at line 39: the shipped demo drew
    `self.pool -> self.stem`, one of four forward edges pointing backwards, and
    the real `relu -> self.pool` edge missing.

    With `exclude` (the call being resolved) the store that call *itself*
    produced is skipped - FW-REBIND. `ds = ds.map(...)` is the binding style the
    official tf.data guide writes, and the flat map answered the `ds` on the
    right-hand side with the store the very same statement was about to write:
    the receiver became its own producer, `_canonical_for_receiver` had an
    untagged, producer-less value to work from, and the call resolved to
    nothing. Six-call pipelines measured 2 nodes / 0 edges in that style
    against 7 nodes / 5 edges written fluently, with no diagnostic at all. The
    right-hand side of `x = f(x)` is evaluated before the name is rebound, so
    skipping the call's own store is what Python itself does; it is a stronger
    guard than `at` alone, which a multi-line assignment defeats (the store's
    line is the statement's, the call's is further down).

    The ordered lookup applies only to the consumer's **own** scope, and never
    to a class scope: a `self.x` store lives in the class scope and is read
    from methods that run in any order, so statement order says nothing there.
    When a name has several stores in that scope and none precedes the
    consumer, the value is a parameter (or a previous iteration): inside a loop
    the last store is the honest answer, and outside one the name is local and
    unwritten, so nothing is returned rather than an outer scope's value.
    """
    if not name or scope is None:
        return None
    cur: Optional[ScopeIR] = scope
    first = True
    while cur is not None:
        if first and cur.kind != "class" and (at is not None or exclude is not None):
            history = cur.binding_history.get(name)
            if history and (len(history) > 1 or _produced_by(history[-1], exclude)):
                picked = _store_before(history, at, exclude)
                if picked is not None:
                    return picked
                fallback = cur.bindings.get(name)
                if _produced_by(fallback, exclude):
                    return None
                if (exclude is not None and fallback is not None
                        and all(fallback is not ref for ref in history)):
                    # A value written into the scope by something other than a
                    # statement in it - `propagate_parameters` seeding a
                    # parameter from the caller. `def f(ds): ds = ds.map(...)`
                    # has one store, the call's own, so without this the
                    # parameter the caller established would be lost.
                    return fallback
                return fallback if in_loop else None
        ref = cur.bindings.get(name)
        if ref is not None and not _produced_by(ref, exclude):
            return ref
        if ref is not None:
            return None          # the only store for the name is the call's own
        cur = cur.parent
        first = False
    return _attribute_of_object(name, scope)


def _attribute_of_object(name: str, scope: ScopeIR) -> Optional[ValueRef]:
    """GRAPH-R3: `bundle.model` -> what `Bundle` stores in `self.model`.

    An object is a name in the caller's scope and its fields are names in its
    **class's** scope, and nothing joined the two: a `@dataclass Bundle(model,
    optimizer)` handed around a training script - or any plain class that does
    `self.model = model` in `__init__` - answered nothing for `bundle.model`,
    so `bundle.model(x)` drew no node and `bundle.optimizer.step()` resolved to
    no symbol. The class scope is exactly where `bindings._store` already
    redirects every `self.*` store, and where DATAFLOW-IP's CONSTRUCTOR summary
    writes the arguments a construction site passed.

    One level, and only for a **workspace class the base name resolves to**, so
    no FQN is invented and `cfg.paths` (a config value, not an object) is
    untouched. `self.` is never re-entered: a method's own `self.x` was
    answered by the class-scope walk above, several lines earlier.
    """
    base, _dot, attr = name.rpartition(".")
    if not base or not attr or base.startswith("self"):
        return None
    holder = binding_of(base, scope)
    cls = holder.class_ir if holder is not None else None
    if cls is None or cls.scope is None:
        return None
    return (cls.scope.bindings.get("self.%s" % attr)
            or cls.scope.bindings.get(attr))


def _produced_by(ref: Optional[ValueRef], call: Optional[CallSite]) -> bool:
    """Is `ref` the store the call being resolved is about to write?"""
    return call is not None and ref is not None and ref.producer is call


def _store_before(history: Sequence[ValueRef], line: Optional[int],
                  exclude: Optional[CallSite] = None) -> Optional[ValueRef]:
    """The last store written strictly above `line`, else None.

    Strictly above, because the right-hand side of `x = f(x)` is evaluated
    before the name is rebound: the consumer on that line reads the *previous*
    value, which is exactly the edge the flat map inverted. A store the
    `exclude` call produced is never picked, whatever its line says.
    """
    picked: Optional[ValueRef] = None
    for ref in history:
        if _produced_by(ref, exclude):
            continue
        loc = ref.loc
        if line is not None and (loc is None or loc.line >= line):
            continue
        picked = ref
    return picked


def _class_scope(scope: ScopeIR) -> Optional[ScopeIR]:
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        if cur.kind == "class":
            return cur
        cur = cur.parent
    return None


def _store(scope: ScopeIR, name: str, ref: ValueRef) -> None:
    target = scope
    if name.startswith("self."):
        target = _class_scope(scope) or scope
    ref.scope = target
    target.bindings[name] = ref
    # REV-01: the ordered record, appended in the source order `bind_module`
    # walks `module.assignments` in. `bindings` keeps its last-wins meaning, so
    # every caller that does not pass a consumer line is byte-for-byte
    # unchanged.
    target.binding_history.setdefault(name, []).append(ref)


def names_in(node: Optional[ast.AST]) -> Tuple[str, ...]:
    """Every name / dotted name read by an expression, in source order."""
    if node is None:
        return ()
    out: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            text = dotted_text(child)
            if text and text not in out:
                out.append(text)
        elif isinstance(child, ast.Name):
            if child.id not in out:
                out.append(child.id)
    return tuple(out)
