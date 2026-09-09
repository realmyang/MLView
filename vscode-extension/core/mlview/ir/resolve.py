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
"""

from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .. import knowledge as K
from .bindings import TENSOR_ROLES, binding_of, call_output_tags
from .model import CallSite, ClassIR, ModuleIR, ScopeIR, ValueRef, sort_tags
from .returns import slot_of
from .symbols import dotted_text

__all__ = ["resolve_calls", "seed_annotations", "propagate_parameters", "mark_fitted"]

#: Receiver bases for values that are plain data frames / arrays.
_FRAME_BASES = ("pandas.DataFrame", "pandas.Series", "numpy.ndarray")

_FAMILY_BASE = {
    "module": "torch.nn.Module",
    "loss": "torch.nn.Module",
    "optimizer": "torch.optim.Optimizer",
    "scheduler": "torch.optim.lr_scheduler.LRScheduler",
    "grad_scaler": "torch.amp.GradScaler",
    "tensor": "torch.Tensor",
    "estimator": "sklearn.base.BaseEstimator",
    "splitter": "sklearn.model_selection.BaseCrossValidator",
    "keras_model": "keras.Model",
    "hf_trainer": "transformers.Trainer",
    "lightning_trainer": "pytorch_lightning.Trainer",
    "argparse": "argparse.ArgumentParser",
    "loader": "torch.utils.data.DataLoader",
    "dataset": "torch.utils.data.Dataset",
    # FW-RECOG (11.23). Each of these is what carries a *chain*: the value the
    # previous link returned has no name to look up, so the family is the only
    # thing that says `.map` here is `tensorflow.data.Dataset.map`.
    "tf_dataset": "tensorflow.data.Dataset",
    "hf_dataset": "datasets.Dataset",
    "keras_dataset": "tensorflow.data.Dataset",
    "lightning_module": "pytorch_lightning.LightningModule",
}


def _class_scope(scope: ScopeIR) -> Optional[ScopeIR]:
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        if cur.kind == "class":
            return cur
        cur = cur.parent
    return None


# ---------------------------------------------------------------------------
# receiver resolution
# ---------------------------------------------------------------------------

def _local_lookup(module: ModuleIR, scope: ScopeIR, name: str):
    """A class or function defined in this module, visible from `scope`."""
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        qual = "%s.%s" % (cur.qualname, name)
        if qual in module.classes:
            return module.classes[qual], None
        if qual in module.functions:
            return None, module.functions[qual]
        cur = cur.parent
    return None, None


def _producer_entry(ref: ValueRef):
    if ref.via_fqns:
        entry, fqn = K.best_entry(ref.via_fqns)
        if entry is not None:
            return entry, fqn
    producer = ref.producer
    if producer is None:
        return None, None
    return K.best_entry(producer.canonical_fqns or ((producer.fqn,) if producer.fqn else ()))


def _family_of_ref(ref: ValueRef) -> Optional[str]:
    """Which receiver family this value belongs to (`module`, `tensor`, ...)."""
    entry, _fqn = _producer_entry(ref)
    if entry is not None and entry["role"] in TENSOR_ROLES:
        return "tensor"
    if ref.class_ir is not None:
        # FW-RECOG: a LightningModule answers to its own method surface first.
        # It *is* an nn.Module, so without this `self.log(...)` would resolve
        # through `torch.nn.` and prefix-match to role LAYER - a layer node in
        # the Model lane for a logging call, the same fabrication 11.19 A2 shut
        # down for `self.loss_fn`.
        if ref.class_ir.is_hook_owner:
            return "lightning_module"
        if ref.class_ir.is_nn_module:
            return "module"
        bases = ref.class_ir.resolved_bases
        if any(b.startswith("torch.utils.data.") for b in bases):
            return "dataset"
        if any(b.startswith("sklearn.") for b in bases):
            return "estimator"
    if entry is not None and entry["family"]:
        return entry["family"]
    if ref.has("LOSS", "LOGITS", "PROBS", "PREDS", "BATCH"):
        return "tensor"
    if ref.has("MODEL"):
        return "module"
    if ref.has("OPTIMIZER"):
        return "optimizer"
    if ref.has("LOADER"):
        return "loader"
    if ref.has("DEVICE"):
        return "device"
    if ref.has("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT",
               "TEST_SPLIT"):
        return "frame"
    return None


def _is_class_like(entry, producer_fqn: str) -> bool:
    """May `<producer FQN>.<method>` name a real symbol?

    Only when the producer is a *class* (a knowledge row with a receiver
    family) and is not itself a method. `cross_val_score` is a plain function,
    so `sklearn.model_selection.cross_val_score.mean` does not exist - and the
    `sklearn.model_selection.` prefix rule would happily classify it as a
    `split` node in the Data lane (CONTRACTS section 1: `Node.fqn` is a
    "canonical third-party symbol").
    """
    if entry is None or not entry.get("family"):
        return False
    if entry["role"] in TENSOR_ROLES:
        return False
    return producer_fqn not in K.METHODS


#: Frameworks whose objects really are `torch.nn.Module` subclasses.
_TORCH_FRAMEWORKS = ("torch", "torchvision", "lightning", "hf", "torchmetrics")


def _is_torch_module(ref: ValueRef, entry, family: Optional[str], method: str) -> bool:
    """May `torch.nn.Module.<method>` be proposed for this receiver?

    The MODEL tag alone is not enough: an sklearn estimator carries it too, and
    `torch.nn.` prefix-matches *any* attribute, so an ungated candidate invents
    symbols like `torch.nn.Module.predict` - which then mislanes the node into
    the Model lane and adds a phantom `torch` framework to a pure-sklearn file.
    """
    if K.lookup_exact("torch.nn.Module.%s" % method) is not None:
        return True                  # a real nn.Module method, whoever the receiver is
    if ref.class_ir is not None and ref.class_ir.is_model_module:
        return True
    if family in ("module", "loss", "lightning_module") and entry is not None:
        if entry.get("framework") in _TORCH_FRAMEWORKS:
            return True
    return False


def _canonical_for_receiver(ref: ValueRef, method: str) -> Tuple[str, ...]:
    """`obj.m()` -> [<producer FQN>.m, <family base>.m, ...] in specificity order."""
    out: List[str] = []
    family = _family_of_ref(ref)
    entry, producer_fqn = _producer_entry(ref)
    tensor_like = family == "tensor"
    torch_module = _is_torch_module(ref, entry, family, method)

    if not tensor_like:
        if producer_fqn and _is_class_like(entry, producer_fqn):
            out.append("%s.%s" % (producer_fqn, method))
        elif ref.class_ir is not None:
            out.append("%s.%s" % (ref.class_ir.qualname, method))
    if ref.class_ir is not None:
        candidate = "%s.%s" % (ref.class_ir.qualname, method)
        if candidate not in out:
            out.append(candidate)

    # FW-RECOG. When the receiver's own workspace class **declares** this
    # method, a framework base may only be proposed for it if that base really
    # publishes the symbol. `def encode(self, x)` on an nn.Module subclass used
    # to produce `torch.nn.Module.encode`, which prefix-matches `torch.nn.` to
    # role LAYER and drew a layer node for a helper the framework never heard
    # of. `torch.nn.Module.forward` survives because it is an exact row; the
    # invented ones do not. Same iron law 1 as 11.19 A2, one level up.
    declared = (ref.class_ir is not None
                and method in (getattr(ref.class_ir, "methods", None) or {}))

    def add(candidate: str) -> None:
        if not candidate or candidate in out:
            return
        if declared and K.lookup_exact(candidate) is None:
            return
        out.append(candidate)

    if family == "frame":
        # A DataFrame / ndarray has no constructor to hang the method off, so
        # only *known* frame methods are proposed - never a fabricated symbol.
        for base in _FRAME_BASES:
            candidate = "%s.%s" % (base, method)
            if K.lookup_exact(candidate) is not None:
                add(candidate)
    base = _FAMILY_BASE.get(family or "")
    if base and (base != "torch.nn.Module" or torch_module):
        add("%s.%s" % (base, method))
    if family in ("estimator", "splitter"):
        add("sklearn.base.BaseEstimator.%s" % method)
    if ref.has("MODEL") and torch_module:
        add("torch.nn.Module.%s" % method)
    if ref.has("OPTIMIZER"):
        add("torch.optim.Optimizer.%s" % method)
    if tensor_like or ref.has("LOSS", "LOGITS", "PROBS", "PREDS", "BATCH"):
        add("torch.Tensor.%s" % method)

    seen: List[str] = []
    for fqn in out:
        if fqn and fqn not in seen:
            seen.append(fqn)
    return tuple(seen)


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


def _annotation_class(module: ModuleIR, workspace, scope: ScopeIR,
                      fqn: str) -> Optional[ClassIR]:
    """`def validate(model: Net, ...)` -> the workspace `ClassIR` for `Net`."""
    if not fqn:
        return None
    if workspace is not None:
        found = workspace.classes.get(fqn)
        if found is not None:
            return found
    cls, _fn = _local_lookup(module, scope, fqn.split(".")[-1])
    return cls


def seed_annotations(module: ModuleIR, workspace=None) -> None:
    """`def validate(model: nn.Module, ...)` gives `model` the MODEL tag.

    A workspace-local annotation (`model: Net`) resolves through the class
    registry, which is what lets an eval helper that is never called still
    know that `model(...)` is a forward pass.
    """
    for func in module.functions.values():
        for param, fqn in func.annotations.items():
            tags = list(K.tags_of(fqn))
            cls = _annotation_class(module, workspace, func.scope, fqn)
            if cls is not None:
                if cls.is_model_module:
                    tags.append("MODEL")
                elif any(b.startswith("torch.utils.data.") for b in cls.resolved_bases):
                    tags.append("RAW_DATA")
            entry = K.lookup(fqn)
            if cls is None and entry is None and not tags:
                continue
            existing = func.scope.bindings.get(param)
            if existing is not None and (existing.tags or existing.class_ir is not None):
                continue
            # FW-RECOG: an annotation that names a **known third-party class**
            # carries its receiver family, not only its tags. `def fit(model:
            # keras.Model, ...)` used to leave `model` with the MODEL tag and
            # nothing else, so `model.fit(...)` fell through to the MODEL-tag
            # fallback, proposed `torch.nn.Module.fit`, prefix-matched
            # `torch.nn.` to role LAYER - and drew a torch layer node in a
            # pure-Keras file. The FQN the annotation states is the answer.
            func.scope.bindings[param] = ValueRef(
                name=param, scope=func.scope, tags=sort_tags(tags), loc=func.loc,
                class_ir=cls, via_fqns=(fqn,) if entry is not None else ())


def propagate_parameters(module: ModuleIR, workspace) -> None:
    """One level of module-local function summaries: arg tags -> parameters.

    `train(model, loader)` gives `train`'s `model` parameter the MODEL tag it
    has at the call site, so `model.eval()` inside resolves.
    """
    for call in module.calls:
        func = call.target_function
        if func is None:
            continue
        params = list(func.params)
        if func.is_method and params and params[0] == "self":
            params = params[1:]
        pairs = []
        for index, arg in enumerate(call.args):
            if index >= len(params):
                break
            pairs.append((params[index], arg))
        for key in sorted(call.kwarg_nodes):
            if key in params:
                pairs.append((key, call.kwarg_nodes[key]))
        for param, arg in pairs:
            name = dotted_text(arg)
            ref = binding_of(name, call.scope) if name else None
            if ref is None or not (ref.tags or ref.class_ir):
                continue
            existing = func.scope.bindings.get(param)
            if existing is not None and (existing.tags or existing.class_ir):
                continue
            func.scope.bindings[param] = ValueRef(
                name=param, scope=func.scope, tags=ref.tags, producer=ref.producer,
                loc=func.loc, class_ir=ref.class_ir, is_config=ref.is_config)


def mark_fitted(module: ModuleIR) -> None:
    """A transformer that has been `.fit()` on carries FITTED_TRANSFORMER.

    Runs after the final binding pass, because that pass rebuilds every
    `ValueRef` from scratch.
    """
    for call in module.calls:
        if K.role_of(call.fqn) not in ("FIT", "FIT_TRANSFORM"):
            continue
        ref = binding_of(call.receiver_name, call.scope, exclude=call) or call.receiver
        if ref is not None:
            ref.add_tags(("FITTED_TRANSFORMER",))


def _value_of_call(inner: CallSite, scope: ScopeIR, name: str) -> ValueRef:
    """A `ValueRef` standing for the value an inline call produced."""
    ref = ValueRef(name=name or "<call>", scope=scope,
                   tags=call_output_tags(inner, scope), producer=inner,
                   loc=inner.loc, class_ir=inner.class_ir)
    slot = slot_of(inner)
    if slot is not None:
        ref.via_fqns = slot.fqns
        ref.class_ir = ref.class_ir or slot.class_ir
    return ref


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


def _resolve_one(call: CallSite, module: ModuleIR, workspace) -> None:
    fqn = _workspace_fqn(workspace, getattr(call, "import_fqn", call.fqn))
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
