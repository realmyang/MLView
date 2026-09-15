"""Receiver resolution: `obj.m(...)` -> the canonical FQNs it answers to.

Rules never see a bare attribute name (iron law 1): `model.eval()` is only
`torch.nn.Module.eval` when the binding behind `model` resolves there. This
module turns a receiver into an ordered list of candidate FQNs, most specific
first, and fills in `CallSite.receiver` / `class_ir` / `target_function`.

It also carries the three small cross-call passes that need the same
machinery: parameter annotations (`seed_annotations`), one level of argument
-> parameter summaries (`propagate_parameters`) and the fitted-transformer
mark (`mark_fitted`).

Split out of `bindings.py`, which owns the other direction: assignments ->
`ValueRef`s. The dependency runs one way, `resolve` -> `bindings`.

Two modules carry what is not the resolution of a single call:
`ir/resolve_receivers.py` answers "what could this receiver be?" (the family
tables and the candidate walk), and `ir/resolve_passes.py` holds the three
cross-call passes. Both are re-exported from here, so `resolve_calls`,
`seed_annotations`, `propagate_parameters` and `mark_fitted` are still four
names on one module.
"""

from __future__ import annotations

import ast
from typing import Optional, Tuple

from .. import knowledge as K
from .bindings import binding_of
from .model import CallSite, ClassIR, ModuleIR, ScopeIR, ValueRef, sort_tags
from .resolve_passes import (_value_of_call, mark_fitted,  # noqa: F401
                             propagate_parameters, seed_annotations)
from .resolve_receivers import (_canonical_for_receiver, _class_scope,
                                _local_lookup)
from .symbols import dotted_text

__all__ = ["resolve_calls", "seed_annotations", "propagate_parameters", "mark_fitted"]


def resolve_calls(module: ModuleIR, workspace) -> None:
    """Fill `canonical_fqns`, `receiver`, `class_ir` and `target_function`."""
    by_node = {id(call.node): call for call in module.calls}
    setattr(module, "_calls_by_node", by_node)
    for call in module.calls:
        _resolve_one(call, module, workspace)
        _note_unresolved(call)


def _class_attr_binding(call: CallSite):
    """The class-scope binding behind `<instance>.<attr>`, for the note only.

    `recipe.make_head()` where `make_head: Callable = field(default_factory=...)`
    is a dataclass attribute: the binding exists, in the *class* scope, and
    holds nothing the analyzer can call. `_attribute_callable` deliberately
    refuses it (it has no producer FQN to offer, iron law 1), which is correct
    for resolution and is exactly why the call used to vanish in silence.
    """
    func = call.node.func
    if not isinstance(func, ast.Attribute):
        return None
    base = dotted_text(func.value)
    if not base:
        return None
    ref = binding_of(base, call.scope, at=call.loc.line, exclude=call)
    cls = ref.class_ir if ref is not None else None
    if cls is None or cls.scope is None:
        return None
    return (cls.scope.bindings.get(func.attr)
            or cls.scope.bindings.get("self.%s" % func.attr))


def _note_unresolved(call: CallSite) -> None:
    """ANA-5a: a callee that is a real binding with nothing behind it.

    The syntactic half (`the result of another call`, `a subscript`, `a
    lambda`) is set at record time by `ir/scopes.callee_construct`. This is the
    other half: a name or attribute chain that resolved to **nothing the
    knowledge tables recognise**, where a binding for it does exist and the
    analyzer could not follow it - a `match`-assigned factory, a lambda-bound
    name, a dataclass `default_factory`.

    The binding is the guard, and it is what keeps this narrow: a builtin such
    as `len` or `range` has no binding in scope, so it is never flagged and no
    `unknown` node is minted for it.
    """
    if (call.unresolved_callee or call.class_ir is not None
            or call.target_function is not None):
        return
    if K.best_entry(call.canonical_fqns)[0] is not None:
        return                       # resolved to something the tables know
    attr = _class_attr_binding(call)
    if attr is not None and attr.opaque:
        call.unresolved_callee = attr.opaque
        return
    if call.receiver is not None:
        # A *method* on an opaque value is still a method; only calling the
        # value itself is the construct ANA-5a is about.
        if call.method == "__call__" and call.receiver.opaque:
            call.unresolved_callee = call.receiver.opaque
        return
    name = dotted_text(call.node.func)
    if not name:
        return
    ref = binding_of(name, call.scope, at=call.loc.line, exclude=call)
    if ref is None:
        return
    if ref.opaque:
        call.unresolved_callee = ref.opaque
        return
    if ref.producer is not None or ref.class_ir is not None or ref.via_fqns:
        return
    call.unresolved_callee = "a value the analyzer could not follow"


def _called_value(call: CallSite, module: ModuleIR) -> Optional[ValueRef]:
    """FW-RECOG: `layers.Dense(64)(x)` - the callee **is** a call.

    The Keras functional API is written this way and nothing else in the
    resolver looked at it, so ANA-5a's syntactic check flagged every functional
    layer as an unresolvable callee and minted an `unknown` node for it - four
    of them in a fifteen-line model. The value the inner call produced is
    already in the IR; calling it is `__call__` on that value, which is what
    the `keras_model` family resolves to `keras.Model.__call__`, role FORWARD,
    and role FORWARD is drawn through its receiver rather than as a node.
    """
    func = call.node.func
    if not isinstance(func, ast.Call):
        return None
    inner = getattr(module, "_calls_by_node", {}).get(id(func))
    if inner is None:
        return None
    return _value_of_call(inner, call.scope, inner.var or inner.short_name)


def _chained_receiver(call: CallSite, module: ModuleIR) -> Optional[ValueRef]:
    """A receiver that is not a name: `Net().to(device)`, `df[cols].to_numpy()`."""
    func = call.node.func
    if not isinstance(func, ast.Attribute):
        return None
    inner_node = func.value
    if isinstance(inner_node, ast.Call):
        inner = getattr(module, "_calls_by_node", {}).get(id(inner_node))
        if inner is None:
            return None
        return _value_of_call(inner, call.scope,
                              inner.var or dotted_text(inner_node) or "<call>")
    if isinstance(inner_node, ast.Subscript):
        # `X = df[cols].to_numpy()` - the subscript preserves the frame's tags,
        # but it is not a name, so there is no binding to look up.
        base = binding_of(dotted_text(inner_node.value), call.scope,
                          at=call.loc.line, exclude=call)
        if base is None:
            return None
        return ValueRef(name=base.name, scope=call.scope, tags=base.tags,
                        producer=base.producer, loc=base.loc,
                        class_ir=base.class_ir, via_fqns=base.via_fqns)
    return None


def _attribute_callable(receiver_name: str, method: str, scope: ScopeIR,
                        call: Optional[CallSite] = None) -> Optional[ValueRef]:
    """ANA-2: the value held in `<receiver>.<attr>`, when it is callable.

    `self.loss_fn(logits, labels)` is not *a method named `loss_fn` on an
    `nn.Module`* - it is a **call on the value bound to that attribute**, and
    that value is already in the IR: `binding_of("self.loss_fn", scope)` hands
    back a `ValueRef` whose producer is `torch.nn.CrossEntropyLoss`. Before
    this, the resolver never consulted the binding and proposed
    `torch.nn.Module.loss_fn`, which prefix-matches to role LAYER - so the same
    criterion fired MLV401 when held in a local and nothing at all when held on
    `self`.

    Iron law 1 holds: the candidate comes from a **real binding**, never from a
    name. A binding with nothing behind it (`self.threshold = 0.5`) is refused,
    so no FQN is invented for it.
    """
    if not receiver_name or not method or method == "__call__":
        return None
    ref = binding_of("%s.%s" % (receiver_name, method), scope, exclude=call)
    if ref is None:
        return None
    if ref.class_ir is not None or ref.via_fqns:
        return ref
    producer = ref.producer
    if producer is not None and (producer.canonical_fqns or producer.fqn):
        return ref
    return None


def _workspace_fqn(workspace, fqn: Optional[str]) -> Optional[str]:
    """ANA-3: the definition a workspace name points at, through re-exports.

    `from pkg import Net` resolves to `pkg.Net`, which no `ClassIR` carries -
    the class is `pkg.net.Net`. `workspace.reexports` holds the already-walked
    chain, so this is one dict hit and never a search.
    """
    if not fqn or workspace is None:
        return fqn
    if fqn in workspace.classes or fqn in workspace.functions:
        return fqn
    return getattr(workspace, "reexports", {}).get(fqn, fqn)


#: ROB-17. `functools.partial` is how a project pins a constructor's keywords
#: once and reuses it, and it was the one factory shape that left no trace at
#: all: a workspace helper keeps the loader, a `lambda` keeps it and raises
#: `unresolved_callee`, a dict lookup loses it but raises `unresolved_callee` -
#: `partial` lost it and raised **nothing**, so `stages[data].present` came
#: back false with an empty `diagnostics` list on a file whose sixth line
#: builds a `DataLoader`. A partial is not an inference: `partial(F, **kw)(x)`
#: *is* `F(x, **kw)`, so the callee and the pinned keywords both travel.
_PARTIAL_FQNS = ("functools.partial", "functools.partialmethod")


def _partial_source(ref: Optional[ValueRef]) -> Optional[CallSite]:
    """The `partial(...)` call behind a name, if that is what bound it."""
    if ref is None or ref.producer is None:
        return None
    producer = ref.producer
    fqn = producer.fqn or ""
    if fqn in _PARTIAL_FQNS or producer.short_name in ("partial", "partialmethod"):
        if producer.args:
            return producer
    return None


def _apply_partial(call: CallSite, source: CallSite, module: ModuleIR,
                   workspace) -> bool:
    """Resolve `call` as if it were a direct call of the partial's target."""
    target = source.args[0]
    symbols = getattr(module, "symbols", None)
    fqn = symbols.resolve(target) if symbols is not None else None
    fqn = _workspace_fqn(workspace, fqn) if fqn else None
    resolved = False
    if fqn:
        cls = workspace.classes.get(fqn) if workspace is not None else None
        fn = workspace.functions.get(fqn) if workspace is not None else None
        if cls is not None:
            call.class_ir = cls
            call.canonical_fqns = _class_canonical(cls, fqn)
            call.fqn = call.canonical_fqns[0] if call.canonical_fqns else fqn
            resolved = True
        elif fn is not None:
            call.target_function = fn
            call.fqn = fqn
            call.canonical_fqns = (fqn,)
            resolved = True
        else:
            call.canonical_fqns = (fqn,)
            call.fqn = fqn
            resolved = K.lookup(fqn) is not None
    if not resolved:
        return False
    # The pinned keywords are part of the call the source really makes, and
    # MLV110 / MLV111 / MLV112 / MLV602 all read them. A keyword written at the
    # call site wins, exactly as Python's own override order says.
    for key in sorted(source.kwargs):
        call.kwargs.setdefault(key, source.kwargs[key])
    for key in sorted(source.kwarg_nodes):
        call.kwarg_nodes.setdefault(key, source.kwarg_nodes[key])
    call.receiver = None
    call.receiver_name = None
    call.method = None
    call.unresolved_callee = None
    return True


def _resolve_one(call: CallSite, module: ModuleIR, workspace) -> None:
    # VIS2-10 / DGRG2-13: a framework class that IS the torch class answers to
    # the torch FQN, so every rule keyed on the canonical name applies to it.
    fqn = K.canonical_alias(_workspace_fqn(
        workspace, getattr(call, "import_fqn", call.fqn)))
    node = call.node
    func = node.func

    # 1. resolved through the import table
    if fqn:
        cls = workspace.classes.get(fqn)
        if cls is not None:
            call.class_ir = cls
            call.canonical_fqns = _class_canonical(cls, fqn)
            _mark_forward(call, workspace)
            return
        fn = workspace.functions.get(fqn)
        if fn is not None:
            call.target_function = fn
            call.canonical_fqns = (fqn,)
            return
        call.canonical_fqns = (fqn,)
        _mark_forward(call, workspace)
        return

    # 2. a class or function defined in this module
    simple = func.id if isinstance(func, ast.Name) else None
    if simple:
        cls, fn = _local_lookup(module, call.scope, simple)
        if cls is not None:
            call.class_ir = cls
            call.fqn = cls.qualname
            call.canonical_fqns = _class_canonical(cls, cls.qualname)
            _mark_forward(call, workspace)
            return
        if fn is not None:
            call.target_function = fn
            call.fqn = fn.qualname
            call.canonical_fqns = (fn.qualname,)
            return

    # 2b. ROB-17: a name bound to `functools.partial(F, ...)` calls F.
    if simple or isinstance(func, ast.Attribute):
        bound = binding_of(dotted_text(func), call.scope, at=call.loc.line,
                           exclude=call)
        source = _partial_source(bound)
        if source is not None and _apply_partial(call, source, module, workspace):
            _mark_forward(call, workspace)
            return

    # 3. a call *of* a call - the Keras functional API (FW-RECOG)
    called = _called_value(call, module)
    if called is not None:
        call.receiver = called
        call.receiver_name = call.receiver_name or called.name
        call.method = "__call__"
        call.canonical_fqns = _canonical_for_receiver(called, "__call__")
        entry, best = K.best_entry(call.canonical_fqns)
        call.fqn = best or (call.canonical_fqns[0] if call.canonical_fqns else None)
        if entry is not None:
            # Resolved after all: ANA-5a's syntactic flag was a first guess and
            # this is the answer. A callee that still resolves to nothing keeps
            # the flag and is drawn as `unknown`.
            call.unresolved_callee = None
        cls = called.class_ir
        if cls is not None and "forward" in cls.methods:
            call.target_function = cls.methods["forward"]
        return

    # 4. a method / call on a bound value
    receiver_name, method = call.receiver_name, call.method
    if receiver_name is None and simple:
        receiver_name, method = simple, "__call__"
    ref = _chained_receiver(call, module)
    if ref is None:
        if receiver_name is None or method is None:
            return
        # ANA-2: an attribute that *holds* a callable answers before the
        # receiver's own family does - `self.loss_fn` is the criterion, not a
        # method on the module that stores it.
        held = _attribute_callable(receiver_name, method, call.scope, call)
        if held is not None:
            call.receiver_name = "%s.%s" % (receiver_name, method)
            ref, method = held, "__call__"
        else:
            ref = binding_of(receiver_name, call.scope, at=call.loc.line,
                             exclude=call)
    elif method is None:
        return
    if ref is None and receiver_name == "self":
        attr_ref = binding_of("self.%s" % method, call.scope, exclude=call)
        if attr_ref is not None:
            ref, method = attr_ref, "__call__"
            call.receiver_name = "self.%s" % call.method
    if ref is None:
        cls_scope = _class_scope(call.scope)
        if cls_scope is not None and receiver_name == "self":
            cls = module.classes.get(cls_scope.qualname)
            if cls is not None and method in cls.methods:
                call.target_function = cls.methods[method]
                call.fqn = "%s.%s" % (cls.qualname, method)
                call.canonical_fqns = (call.fqn,)
        return
    call.receiver = ref
    call.method = method
    call.canonical_fqns = _canonical_for_receiver(ref, method)
    _entry, best = K.best_entry(call.canonical_fqns)
    call.fqn = best or (call.canonical_fqns[0] if call.canonical_fqns else None)
    cls = ref.class_ir
    if cls is not None and method in cls.methods:
        call.target_function = cls.methods[method]
    if cls is not None and method == "__call__" and "forward" in cls.methods:
        call.target_function = cls.methods["forward"]
    if K.role_of(call.fqn) in ("FIT", "FIT_TRANSFORM"):
        ref.add_tags(("FITTED_TRANSFORMER",))


def _class_canonical(cls: ClassIR, fqn: str) -> Tuple[str, ...]:
    out = [fqn]
    for base in cls.resolved_bases:
        if base not in out:
            out.append(base)
    return tuple(out)


def _mark_forward(call: CallSite, workspace) -> None:
    """`model(x)` on an nn.Module (or LightningModule) instance is a forward pass."""
    if (call.method == "__call__" and call.class_ir is not None
            and call.class_ir.is_model_module):
        if "torch.nn.Module.__call__" not in call.canonical_fqns:
            call.canonical_fqns = call.canonical_fqns + ("torch.nn.Module.__call__",)
