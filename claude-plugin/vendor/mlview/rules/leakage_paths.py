"""The dataflow walks the three leakage rules share.

Split out of `rules/r_leakage.py`, which keeps the three `@rule` entry points -
`RuleSpec.module` is part of every rule page and must not move. What lives here
is the *path finding*: given a fit site or a cross-validation call, which split
consumes its value, and did the value have to cross a `def` to get there.

Four walks, three of them interprocedural and each paying its own hop:

    _split_consuming        the split in the fit's own scope (both modes)
    _split_after_return     the split in the CALLER, reached by a `return`
    _fold_projection        `X[test_idx]`, the held-out half of a CV fold
    _callee_fit_transform   the `fit_transform` inside the helper that made X

`_cross_scope_split` and `_note_refused_split` are the fifth thing: the
*refusal*. A cross-scope match the scope guard rejected is a gap, not a clean
read, and 11.36 N5 says so out loud rather than going quiet.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from ..core.graph import Diagnostic
from ..ir.model import CallSite, ValueRef
from ..ir.provenance import DEFAULT_MAX_HOPS, Hop, extend
from ..ir.symbols import dotted_text
from ..knowledge import STATELESS_TRANSFORMERS
from .helpers import DATA_TAGS, arg_ref, reaches

__all__ = ["split_consuming", "split_after_return", "fold_projection",
           "callee_fit_transform", "note_refused_split", "FOLD_TEST_POSITION"]

def cross_scope_split(ctx, fit: CallSite, splits, targets,
                       ref) -> Optional[CallSite]:
    """The split that a *scope* guard - and only a scope guard - rejected.

    Two shapes, both of them a refusal rather than a clean read:

    1. a split written in another scope of the fit's own module whose argument
       still reaches the fitted value by name (the shape the scope guard exists
       to reject), and
    2. a split at or after the line the tag **entered** this scope through -
       `Scaled(X)` in the caller, `train_test_split(...)` on the next line.
       That is the commonest cross-object leak shape there is, and no name path
       joins the two halves, so only the hop's own location can find it.
    """
    for split in splits:
        if split.module is not fit.module or split.scope is fit.scope:
            continue
        for arg in list(split.args) + [split.kwarg_nodes[k] for k in sorted(split.kwarg_nodes)]:
            name = dotted_text(arg)
            if name and reaches(ctx, name, split.scope, targets):
                return split
    best: Optional[CallSite] = None
    for hop in getattr(ref, "provenance", ()) or ():
        loc = getattr(hop, "loc", None)
        if loc is None:
            continue
        for split in splits:
            if split.loc.file != loc.file or split.loc.line < loc.line:
                continue
            if split.scope is fit.scope:
                continue
            if best is None or (split.loc.line, split.loc.col) < (best.loc.line, best.loc.col):
                best = split
    return best


def note_refused_split(ctx, fit: CallSite, name: Optional[str], ref, splits) -> None:
    """IP-02: disclose a cross-object match the scope guard refused.

    Only for a value whose tag arrived through an interprocedural hop. A local
    value that finds no split in its own scope is an ordinary clean read, and
    a note on every one of those would be noise rather than candour; a value
    that travelled into this scope and whose only candidate split is written
    somewhere else is a *refusal*, and 11.36 N5 already requires DATAFLOW-IP to
    say so for the hop cap. This is the same class of refusal.
    """
    if not getattr(ref, "provenance", ()):
        return
    targets = {name, fit.var}
    split = cross_scope_split(ctx, fit, splits, targets, ref)
    if split is None:
        return
    spec = getattr(ctx, "current_rule", None)
    message = (
        "%s found a later %s at %s:%d, but `%s` reached %s only through an "
        "interprocedural hop (%s), so the cross-scope match was refused: "
        "leakage through `%s` is neither confirmed nor ruled out."
        % (spec.code if spec is not None else "MLView", split.short_name,
           split.loc.file, split.loc.line, name or "the value",
           fit.scope.qualname if fit.scope is not None else "this scope",
           ctx.hop_chain(ref) or "one hop", name or "it"))
    for existing in ctx.diagnostics:
        if existing.kind == "truncated" and existing.message == message:
            return
    ctx.diagnostics.append(Diagnostic(
        kind="truncated", message=message, file=fit.loc.file, line=fit.loc.line,
        scope=fit.scope.qualname if fit.scope is not None else None,
        ruleCode=spec.code if spec is not None else None))


def _returned_call(func, element) -> Optional[CallSite]:
    """The `CallSite` behind a `return <call>`, when the analyzer resolved one.

    `dotted_text` yields None for an `ast.Call`, which used to end both
    interprocedural leakage walks before they looked at anything: a helper
    written `return scaler.fit_transform(frame)` - the idiomatic spelling -
    produced an empty position list, while the same helper refactored to
    `matrix = scaler.fit_transform(frame); return matrix` produced a finding.
    The two spellings are the same program and now read the same.
    """
    if not isinstance(element, ast.Call):
        return None
    index = getattr(func.module, "_calls_by_node", None) or {}
    return index.get(id(element))


def _call_operands(call: Optional[CallSite]) -> List[str]:
    """The dotted names a call is written on - its receiver and its arguments.

    One level, literal, and no deeper: `scaler.fit_transform(frame)` stands for
    `frame` and for `scaler`, which is exactly what the name form of the same
    return would have said.
    """
    if call is None:
        return []
    out: List[str] = []
    for node in list(call.args) + [call.kwarg_nodes[k]
                                   for k in sorted(call.kwarg_nodes)]:
        text = dotted_text(node)
        if text and text not in out:
            out.append(text)
    for text in (call.var, call.receiver_name):
        if text and text not in out:
            out.append(text)
    return out


def _fed_return_positions(ctx, func, produced, fit: Optional[CallSite] = None
                          ) -> List[Optional[int]]:
    """Which returned positions of `func` carry a value derived from the fit.

    `None` in the list means the function returns a scalar rather than a tuple.
    """
    out: List[Optional[int]] = []
    for expr in func.returns:
        tupled = isinstance(expr, (ast.Tuple, ast.List))
        elements = list(expr.elts) if tupled else [expr]
        for index, element in enumerate(elements):
            text = dotted_text(element)
            fed = bool(text) and reaches(ctx, text, func.scope, produced)
            if not fed:
                # `return scaler.fit_transform(frame)`: `dotted_text` gives the
                # *callee* (`scaler.fit_transform`), which reaches nothing, so
                # the call itself is what has to be read.
                call = _returned_call(func, element)
                fed = call is not None and (
                    call is fit
                    or any(reaches(ctx, operand, func.scope, produced)
                           for operand in _call_operands(call)))
            if not fed:
                continue
            slot = index if tupled else None
            if slot not in out:
                out.append(slot)
    return out


def _callers_of(ctx, func) -> List[CallSite]:
    out: List[CallSite] = []
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            if call.target_function is func:
                out.append(call)
    out.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return out


def split_after_return(ctx, fit: CallSite, splits, name: Optional[str], ref):
    """`(split, hop ref)` for a fit whose product is split in the *caller*.

    `--dataflow ip` only, and deliberately narrow: the split's argument must be
    bound by the very call site that invoked the fit's function, at a returned
    position the fitted value feeds. No name is matched across scopes - the
    shape REV5-01 forbids - because the binding's own producer *is* the call.
    """
    if getattr(ctx, "dataflow", "local") != "ip":
        return None, None
    func = fit.function
    if func is None:
        return None, None
    produced = {t for t in (fit.var, name) if t}
    if not produced:
        return None, None
    positions = _fed_return_positions(ctx, func, produced, fit)
    if not positions:
        return None, None
    for caller in _callers_of(ctx, func):
        for split in splits:
            if split.module is not caller.module or split.scope is not caller.scope:
                continue
            if split.loc.line < caller.loc.line:
                continue
            for arg in list(split.args) + [split.kwarg_nodes[k]
                                           for k in sorted(split.kwarg_nodes)]:
                arg_name = dotted_text(arg)
                if not arg_name:
                    continue
                bound = ctx.binding_of(arg_name, split.scope, at=split.loc.line)
                if bound is None or bound.producer is not caller:
                    continue
                if bound.index not in positions:
                    continue
                hop = Hop(kind="return",
                          detail="the value %s() returns into %s"
                          % (func.name, caller.scope.qualname
                             if caller.scope is not None else caller.loc.file),
                          loc=caller.loc)
                chain = extend(getattr(ref, "provenance", ()) or (), hop,
                               getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
                if chain is None:
                    return None, None    # the hop cap; stay silent rather than guess
                returned = ValueRef(name=arg_name, scope=bound.scope, tags=bound.tags,
                                    producer=bound.producer, loc=bound.loc,
                                    sources=bound.sources, class_ir=bound.class_ir,
                                    is_config=bound.is_config, via_fqns=bound.via_fqns,
                                    provenance=chain)
                ctx.note_hops(returned, split.scope)
                return split, returned
    return None, None


def split_consuming(ctx, fit: CallSite, splits, targets) -> Optional[CallSite]:
    """The later split whose input derives from the fit's input or output.

    The split must be written in the fit's own scope (REV5-01): the reachability
    test below matches by dotted **name**, and a name means something else in a
    foreign scope. See `fit_before_split`.
    """
    for split in splits:
        if split.module is not fit.module:
            continue
        if split.scope is not fit.scope:
            continue
        if split.loc.line < fit.loc.line:
            continue
        for arg in list(split.args) + [split.kwarg_nodes[k] for k in sorted(split.kwarg_nodes)]:
            name = dotted_text(arg)
            if not name:
                continue
            if reaches(ctx, name, split.scope, targets):
                return split
    return None



FOLD_TEST_POSITION = 1


def fold_projection(ctx, fit: CallSite):
    """`(text, ref, splitter call)` when the fit's argument is `X[test_idx]`.

    `--dataflow ip` only, and every step has to hold: the argument is a
    subscript, its index is the second name unpacked from a `fold` loop's
    header, that header iterates the very call the index came from, and that
    call is a `SPLIT`. Anything less and the rows are not provably a fold.
    """
    if getattr(ctx, "dataflow", "local") != "ip":
        return None
    node = fit.args[0] if fit.args else fit.kwarg_nodes.get("X")
    if not isinstance(node, ast.Subscript):
        return None
    index_name = dotted_text(node.slice)
    base_name = dotted_text(node.value)
    if not index_name or not base_name:
        return None
    index_ref = ctx.binding_of(index_name, fit.scope, at=fit.loc.line)
    if index_ref is None or index_ref.index != FOLD_TEST_POSITION:
        return None
    loop = fit.loop
    while loop is not None and loop.kind != "fold":
        loop = loop.parent_loop
    if loop is None or (loop.iter_text or "") not in (index_ref.sources or ()):
        return None
    splitter = None
    for call in ctx.calls_with_role("SPLIT"):
        if call.module is fit.module and call.loc.line == loop.loc.line:
            splitter = call
            break
    if splitter is None:
        return None
    base = ctx.binding_of(base_name, fit.scope, at=fit.loc.line)
    if base is None or not base.has(*DATA_TAGS):
        return None
    text = "%s[%s]" % (base_name, index_name)
    hop = Hop(kind="projection", detail="the held-out fold of `%s`" % base_name,
              loc=base.loc or fit.loc)
    chain = extend(getattr(base, "provenance", ()) or (), hop,
                   getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    if chain is None:
        return None                  # the hop cap; stay silent rather than guess
    derived = ValueRef(name=text, scope=base.scope,
                       tags=tuple(base.tags) + ("TEST_SPLIT",),
                       producer=base.producer, loc=base.loc, sources=base.sources,
                       class_ir=base.class_ir, is_config=base.is_config,
                       via_fqns=base.via_fqns, provenance=chain)
    ctx.note_hops(derived, fit.scope)
    return text, derived, splitter



def _returned_names(func, index: Optional[int]) -> List[str]:
    """The names a function hands back, at one tuple position or at all of them.

    A returned **call** stands for the names it is written on (`_call_operands`),
    so `return pca.fit_transform(X)` says `X` the way
    `reduced = pca.fit_transform(X); return reduced` says `reduced`. Without
    that, R15 read only the half of its own rule that happens to bind a name.
    """
    out: List[str] = []
    for expr in func.returns:
        elements = list(expr.elts) if isinstance(expr, (ast.Tuple, ast.List)) else [expr]
        if index is not None and isinstance(expr, (ast.Tuple, ast.List)):
            if index >= len(elements):
                continue
            elements = [elements[index]]
        for element in elements:
            text = dotted_text(element)
            if text and text not in out:
                out.append(text)
            if not isinstance(element, ast.Call):
                continue
            # `dotted_text` of a call is its *callee*, which names no value;
            # the value is what the call was written on.
            for operand in _call_operands(_returned_call(func, element)):
                if operand not in out:
                    out.append(operand)
    return out


def callee_fit_transform(ctx, cv_call: CallSite, data_name: str):
    """`(fit, hop ref)` for a `fit_transform` inside the helper that made X.

    `--dataflow ip` only, and one level only: the CV's `X` is resolved to the
    workspace call that produced it, the callee's `return` is read at the tuple
    position the caller unpacked, and a non-stateless `fit_transform` whose
    output reaches that returned name is the fit whose statistics every fold
    now shares. The hop is minted here rather than read off the ref, because
    the tag did not travel - the *fit site* did, and the finding has to pay for
    the crossing all the same.
    """
    if getattr(ctx, "dataflow", "local") != "ip":
        return None, None
    ref = ctx.binding_of(data_name, cv_call.scope)
    producer = ref.producer if ref is not None else None
    func = getattr(producer, "target_function", None) if producer is not None else None
    if func is None or func is cv_call.function:
        return None, None
    returned = _returned_names(func, getattr(ref, "index", None))
    if not returned:
        return None, None
    best: Optional[CallSite] = None
    for fit in ctx.calls_with_role("FIT_TRANSFORM"):
        if fit.function is not func or _stateless(fit):
            continue
        targets = {fit.var}
        name, _ref = arg_ref(ctx, fit, 0)
        if name:
            targets.add(name)
        if not any(reaches(ctx, returned_name, func.scope, targets)
                   for returned_name in returned):
            continue
        if best is None or fit.loc.line > best.loc.line:
            best = fit
    if best is None:
        return None, None
    hop = Hop(kind="return", detail="the value %s returns from %s()"
              % (data_name, func.name), loc=producer.loc)
    chain = extend(getattr(ref, "provenance", ()) or (), hop,
                   getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    if chain is None:
        return None, None            # the hop cap; stay silent rather than guess
    hop_ref = ValueRef(name=data_name, scope=ref.scope, tags=ref.tags,
                       producer=ref.producer, loc=ref.loc, sources=ref.sources,
                       class_ir=ref.class_ir, is_config=ref.is_config,
                       via_fqns=ref.via_fqns, provenance=chain)
    ctx.note_hops(hop_ref, cv_call.scope)
    return best, hop_ref


def _stateless(call: CallSite) -> bool:
    """A transformer with no fitted state cannot leak one."""
    ref = call.receiver
    producer = ref.producer if ref is not None else None
    fqn = producer.fqn if producer is not None else call.fqn
    return bool(fqn and fqn in STATELESS_TRANSFORMERS)
