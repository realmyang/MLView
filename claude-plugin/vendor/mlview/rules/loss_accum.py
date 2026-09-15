"""MLV205's reading of an accumulator: what it holds, and how long.

Split out of `rules/r_trainloop.py`, which keeps the five `@rule` entry points -
`RuleSpec.module` is part of every rule page and must not move.

Three questions, and the rule is the conjunction of their answers:

    _accumulations       which statements add a tensor to a running total
    _defined_outside     does the accumulator outlive the loop that adds to it
    _backwarded          was the accumulation deliberate - one backward() on it
    _no_grad_region      is there any autograd graph here to keep alive
    _consumed_downstream is the running total the value the code goes on to use

`no_grad_region` and `consumed_downstream` are the two *silencing* readers the
widening to "any accumulating loop" forgot. A loop under `torch.no_grad()` has
no graph to retain, so `running_vloss += vloss` there is correct code; and an
accumulator the program goes on to `backward()` (directly, or through one
arithmetic step - `total = content + style; total.backward()`) or to `return`
out of its own function (a loss module's `forward` collecting per-term losses)
is holding the graph **on purpose**, and taking `.item()` there would silently
stop training. Both may only ever silence MLV205, never raise it.

`_within` lives here because `_defined_outside` is the reader that has to get
it exactly right: "outside the loop" means outside the loop that **accumulates**,
not outside the outermost loop in sight. `total = 0.0` at the top of the epoch
loop with `total += loss` in the batch loop inside it holds a whole epoch of
autograd graphs, and reading the containment the other way round exempted
precisely that shape.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from .. import knowledge as K
from ..ir.model import CallSite, LoopIR, ValueRef
from ..ir.symbols import dotted_text

__all__ = ["accumulations", "defined_outside", "backwarded", "within",
           "no_grad_region", "consumed_downstream"]

_ACCUM_SAFE = ("item", "detach", "float", "cpu", "numpy", "tolist")


def within(loop: Optional[LoopIR], outer: Optional[LoopIR]) -> bool:
    """True when `loop` is `outer` or nested inside it."""
    if outer is None:
        return False
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False



def accumulations(ctx, module):
    """`total += loss`, `total = total + loss` and `losses.append(loss)` in a loop."""
    out = []
    for record in module.assignments:
        if record.loop is None or record.value is None:
            continue
        name = None
        if record.kind == "aug":
            name = dotted_text(record.targets[0]) if record.targets else None
        elif record.kind == "assign" and isinstance(record.value, ast.BinOp):
            for target in record.targets:
                text = dotted_text(target)
                if text and text in _names_of(record.value):
                    name = text
                    break
        if name is None or _guarded(record.value):
            continue
        loss_ref = _loss_operand(ctx, record.value, record.scope, name, module)
        if loss_ref is not None:
            out.append((name, record.loop, record.loc, record.scope, loss_ref,
                        "accumulates"))
    for call in module.calls:
        if (call.method or "") != "append" or call.loop is None or not call.args:
            continue
        name = call.receiver_name
        container = ctx.binding_of(name, call.scope) if name else None
        if container is None or container.literal not in ("[]", "()"):
            continue
        if _guarded(call.args[0]):
            continue
        loss_ref = _loss_operand(ctx, call.args[0], call.scope, name, module)
        if loss_ref is not None:
            out.append((name, call.loop, call.loc, call.scope, loss_ref, "collects"))
    return out


def _names_of(value: ast.expr) -> List[str]:
    out: List[str] = []
    for child in ast.walk(value):
        text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) else None
        if text and text not in out:
            out.append(text)
    return out


def _guarded(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in _ACCUM_SAFE:
            return True
        if isinstance(func, ast.Name) and func.id in ("float", "int", "len", "sum"):
            return True
    return False


def _loss_operand(ctx, value: ast.expr, scope, accumulator: str,
                  module=None) -> Optional[ValueRef]:
    for text in _names_of(value):
        if text == accumulator:
            continue
        if module is not None and _already_detached(module, text, scope):
            continue
        ref = ctx.binding_of(text, scope)
        if ref is not None and ref.has("LOSS"):
            return ref
        if ref is not None and module is not None and _loss_by_arithmetic(
                ctx, module, text, scope):
            return ref
    return None


def _already_detached(module, name: str, scope) -> bool:
    """`total_loss += loss.item()` - a running Python float, not a tensor.

    The LOSS tag reaches `total_loss` because `loss` carries it and the binding
    pass unions the operand's tags; `.item()` is not a call whose output type
    the tables re-state. So the *second* reader - `losses.append(total_loss)` -
    saw a live loss where the author had already taken the scalar. True only
    when the name is written in this scope and **every** write to it is one the
    `_ACCUM_SAFE` guard already accepts, so a name with one unguarded write
    stays exactly as visible as it was.
    """
    seen = False
    for record in module.assignments:
        if record.scope is not scope or record.value is None:
            continue
        if not any(dotted_text(t) == name for t in record.targets):
            continue
        if _initialiser(record.value):
            continue                 # `total_loss = 0.0` puts no tensor in
        seen = True
        if not _guarded(record.value):
            return False
    return seen


def _initialiser(value: ast.expr) -> bool:
    """`0`, `0.0`, `[]`, `()` - the statement that *creates* an accumulator."""
    if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
        return not isinstance(value.value, bool)
    return isinstance(value, (ast.List, ast.Tuple)) and not value.elts


def _loss_by_arithmetic(ctx, module, name: str, scope) -> bool:
    """`loss = criterion(...) / ACCUM_STEPS` still holds the autograd graph.

    Dividing a loss by the accumulation count is how every gradient-accumulation
    tutorial is written, and it is a `BinOp`, so the binding's producer is not
    the criterion call and the LOSS tag never reaches the name. The tensor is
    exactly as live as it was before the division - `running += loss` keeps the
    whole graph either way - so the rule has to read through the arithmetic.

    Only arithmetic: a value the author already took off the graph
    (`.item()`, `.detach()`, `float()`) is `_guarded`, and reading through that
    would accuse correct code.
    """
    for record in module.assignments:
        if record.value is None or record.scope is not scope:
            continue
        if not any(dotted_text(t) == name for t in record.targets):
            continue
        if not isinstance(record.value, (ast.BinOp, ast.UnaryOp)):
            continue
        if _guarded(record.value):
            return False
        for text in _names_of(record.value):
            if text == name:
                continue
            ref = ctx.binding_of(text, scope)
            if ref is not None and ref.has("LOSS"):
                return True
        for child in ast.walk(record.value):
            if not isinstance(child, ast.Call):
                continue
            call = getattr(module, "_calls_by_node", {}).get(id(child))
            if call is None:
                continue
            if "LOSS" in (K.tags_of(call.fqn) or ()):
                return True
            receiver = call.receiver
            if K.role_of(call.fqn) == "FORWARD" and receiver is not None \
                    and receiver.has("LOSS"):
                return True
    return False


def defined_outside(module, name: str, loop: Optional[LoopIR], loc):
    """The statement that created the accumulator outside the loop, if any."""
    best = None
    for other in module.assignments:
        if other.loc.line >= loc.line:
            continue
        if within(other.loop, loop):
            # Created inside the accumulating loop: reset each pass, no defect.
            # The test used to run the other way round (`within(loop,
            # other.loop)`), which also discarded the commonest real shape there
            # is - `total = 0.0` at the top of the **epoch** loop and
            # `total += loss` in the batch loop inside it. That accumulator
            # lives for a whole epoch, which is precisely the leak this rule
            # exists to report, and it was silently exempt.
            continue
        if any(dotted_text(t) == name for t in other.targets):
            best = other
    return best


def backwarded(module, name: str) -> bool:
    """`total_loss.backward()` (or `torch.stack(losses).backward()`) is deliberate.

    The method name counts even when the FQN did not resolve. `total_loss =
    total_loss + loss` binds a `BinOp`, so the accumulator carries no LOSS tag,
    so receiver resolution never proposes `torch.Tensor.backward` for it - and
    the one call that proves the accumulation is on purpose was invisible to
    the guard that exists to read it. A guard may only ever *silence* this
    rule, so reading it by name is safe in the direction that matters.
    """
    short = name.split(".")[-1]
    stacked = set()
    for call in module.calls:
        if (call.fqn or "").endswith(("torch.stack", "torch.cat")) and call.var:
            for arg in call.args:
                if (dotted_text(arg) or "").split(".")[-1] == short:
                    stacked.add(call.var.split(".")[-1])
    wanted = {short} | stacked
    for call in module.calls:
        if K.role_of(call.fqn) != "BACKWARD" \
                and (call.method or call.short_name) != "backward":
            continue
        receiver = (call.receiver_name or "").split(".")[-1]
        if receiver in wanted:
            return True
        for child in ast.walk(call.node):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text and text.split(".")[-1] in wanted:
                return True
    return False


def no_grad_region(loop: Optional[LoopIR]) -> bool:
    """True when the accumulation runs where autograd builds no graph.

    R18(a) widened MLV205 from "the training loop" to *any* accumulating loop
    and so inherited every validation loop ever written:

        with torch.no_grad():
            for vinputs, vlabels in validation_loader:
                running_vloss += loss_fn(model(vinputs), vlabels)

    There is no graph behind `vloss`, so nothing is kept alive and the finding
    is simply wrong. The `with` block and the `@torch.no_grad()` decorator are
    the same fact recorded in two places (`ir.scopes_walk`), so both are read.
    """
    if loop is None:
        return False
    if loop.inside_no_grad:
        return True
    func = loop.function
    return bool(func is not None and func.inside_no_grad)


def consumed_downstream(module, name: str, scope,
                        accumulated: Optional[str] = None) -> bool:
    """True when the program *uses* the running total as a live tensor.

    Two spellings of one intent, and neither is a defect:

    * ``style_loss += mse_loss(...)`` then ``total = content + style_loss``
      then ``total.backward()`` - the accumulation is one operand of the loss
      that is actually backpropagated, one arithmetic step away, which is the
      same single BinOp hop `_loss_by_arithmetic` already reads in the other
      direction; and
    * ``losses.append(term_loss.mean((1,)))`` inside a loss module's own
      ``forward``, which then ``return``s the sum - the caller backpropagates
      it, so `.item()` here would detach the whole loss from training.

    The `return` arm asks one more question than the `backward()` arm, because
    `losses.append(loss)` after `loss.backward()` also ends in `return losses`
    and *is* the defect: when the collected tensor has already been
    backpropagated in this very scope, the running total is a record of the
    epoch rather than the loss, and handing it back keeps every graph alive.

    One level only: a name assigned *directly from* an expression mentioning
    the accumulator, in the accumulator's own scope. Nothing here can raise the
    rule, so a missed derivation costs a false negative and never a false
    positive.
    """
    derived = _derived_names(module, name, scope)
    if any(backwarded(module, candidate) for candidate in derived):
        return True
    if accumulated and backwarded(module, accumulated):
        # The tensor being collected is already backpropagated *here*, so the
        # running total is a record of what happened, not the value the caller
        # will differentiate - `losses.append(loss)` after `loss.backward()`.
        # Handing that record back is exactly the leak MLV205 reports.
        return False
    return _returned(module, derived, scope)


def _derived_names(module, name: str, scope) -> List[str]:
    """`name`, plus every name assigned from an expression that mentions it."""
    out = [name]
    for record in module.assignments:
        if record.scope is not scope or record.value is None:
            continue
        if name not in _names_of(record.value):
            continue
        for target in record.targets:
            text = dotted_text(target)
            if text and text not in out:
                out.append(text)
    return out


def _returned(module, names: List[str], scope) -> bool:
    """Does the function that owns `scope` hand one of `names` back?"""
    wanted = set(names)
    for func in (module.functions or {}).values():
        if func.scope is not scope:
            continue
        for expr in func.returns:
            for child in ast.walk(expr):
                if not isinstance(child, (ast.Name, ast.Attribute)):
                    continue
                text = dotted_text(child)
                if text and text in wanted:
                    return True
    return False
