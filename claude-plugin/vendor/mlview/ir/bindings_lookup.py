"""Name -> `ValueRef`: the binding store and the walk that reads it back.

The map itself is `ScopeIR.bindings`, a flat `name -> one ValueRef`; `_store`
is its only writer and redirects `self.x` onto the owning class scope so a
method's attribute and `__init__`'s are one name. `binding_of` reads it back
*at a line*, walking the scope chain outwards, so a rebound name still answers
with the producer that was in effect where the consumer stands (REV-01) and a
call never resolves to the store it produced itself (FW-REBIND).

Nothing here knows what a call means - that is `ir/bindings_tags.py` - so this
is the bottom of the four-module `ir/bindings.py` stack and imports none of it.
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
            # PUB-01: `len(history) > 1` let the ONE-store case through to the
            # flat map, and the one store can perfectly well be written *below*
            # the consumer - `loss = bce(pred, true)` followed by `pred =
            # torch.sigmoid(pred)`, the shape every focal-loss implementation
            # has. A producer that runs after the use does not reach it (unless
            # a loop carries it round), so a caller that asked for the ordered
            # lookup gets it whenever there is any history at all.
            if history and (len(history) > 1 or _produced_by(history[-1], exclude)
                            or _only_store_is_below(history, at)):
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
    return _holder_field(name, scope, at, exclude)


def _holder_field(name: str, scope: ScopeIR, at: Optional[int],
                  exclude: Optional[CallSite]) -> Optional[ValueRef]:
    """§5.3 A11 (d): `bundle.criterion` is what `Bundle` stores in `self.criterion`.

    The fallback, **once and last**: the scope chain has already said it has no
    binding for this dotted name, and the only thing left that can know is the
    workspace class the base resolves to. `criterion = nn.CrossEntropyLoss()`
    handed to a holder's constructor was reachable from the holder's own
    methods (`self.criterion`) and from nowhere else, so a trainer written as
    `bundle.criterion(model(x), y)` produced no LOSS-tagged value,
    `loss.backward()` back-propagated something MLView could not type, and
    MLV201/202/203/205 - two of them **high** - all skipped the training step
    with only a coverage note. The MODEL half of the same holder never showed
    it, because a model is reached through its own `class_ir`.

    Three things keep it narrow, and they are the clause's own words. **One
    level**: the base is a plain name, never itself a dotted path, so this
    never walks a chain of holders. **Only a workspace class**: the base must
    resolve to a `ClassIR` MLView read, so no FQN is invented for a third-party
    object. **`self.` is never re-entered**: `_store` already redirects a
    method's `self.x` onto the class scope, so that name answers above and
    never reaches here.
    """
    if not name or "." not in name:
        return None
    base, _, attr = name.rpartition(".")
    if not base or not attr or "." in base or base == "self":
        return None
    holder = binding_of(base, scope, at=at, exclude=exclude)
    cls = holder.class_ir if holder is not None else None
    if cls is None or cls.scope is None:
        return None
    return (cls.scope.bindings.get("self.%s" % attr)
            or cls.scope.bindings.get(attr))


def _only_store_is_below(history: Sequence[ValueRef], line: Optional[int]) -> bool:
    """PUB-01: the name's single store is written *below* the consumer.

    `len(history) > 1` used to be the whole entry condition for the ordered
    lookup, so a name with exactly one store went straight to the flat map -
    and that one store can perfectly well run after the use:

        loss = self.loss_fcn(pred, true)     # the consumer
        pred = torch.sigmoid(pred)           # the only store for `pred`

    is the shape of every focal-loss implementation, and MLV402 read the
    sigmoid on the line below as the producer of the line above, emitting high
    / 0.95 with a message whose own line numbers ran backwards. A store below
    the consumer reaches it only round a loop, which is what `in_loop` decides.
    """
    if line is None or len(history) != 1:
        return False
    loc = getattr(history[0], "loc", None)
    return bool(loc is not None and loc.line > line)


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


#: `rebind_projections` re-reads a statement `bind_module` already read, so its
#: stores must **replace** the ones already in `binding_history` rather than
#: append to it - otherwise the ordered lookup (REV-01) would see the same
#: statement twice and a two-store name would report three.
_REBINDING = {"active": False}


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
    history = target.binding_history.setdefault(name, [])
    if _REBINDING["active"]:
        line = ref.loc.line if ref.loc is not None else None
        for index, other in enumerate(history):
            if line is not None and other.loc is not None and other.loc.line == line:
                history[index] = ref
                return
    history.append(ref)


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
