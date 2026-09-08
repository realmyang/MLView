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
    if ref.class_ir is not None and ref.class_ir.is_nn_module:
        return True
    if family in ("module", "loss") and entry is not None:
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

    if family == "frame":
        # A DataFrame / ndarray has no constructor to hang the method off, so
        # only *known* frame methods are proposed - never a fabricated symbol.
        for base in _FRAME_BASES:
            candidate = "%s.%s" % (base, method)
            if K.lookup_exact(candidate) is not None:
                out.append(candidate)
    base = _FAMILY_BASE.get(family or "")
    if base and (base != "torch.nn.Module" or torch_module):
        out.append("%s.%s" % (base, method))
    if family in ("estimator", "splitter"):
        out.append("sklearn.base.BaseEstimator.%s" % method)
    if ref.has("MODEL") and torch_module:
        out.append("torch.nn.Module.%s" % method)
    if ref.has("OPTIMIZER"):
        out.append("torch.optim.Optimizer.%s" % method)
    if tensor_like or ref.has("LOSS", "LOGITS", "PROBS", "PREDS", "BATCH"):
        out.append("torch.Tensor.%s" % method)

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
                if cls.is_nn_module:
                    tags.append("MODEL")
                elif any(b.startswith("torch.utils.data.") for b in cls.resolved_bases):
                    tags.append("RAW_DATA")
            entry = K.lookup(fqn)
            if cls is None and entry is None and not tags:
                continue
            existing = func.scope.bindings.get(param)
            if existing is not None and (existing.tags or existing.class_ir is not None):
                continue
            func.scope.bindings[param] = ValueRef(
                name=param, scope=func.scope, tags=sort_tags(tags), loc=func.loc,
                class_ir=cls)


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
        ref = binding_of(call.receiver_name, call.scope) or call.receiver
        if ref is not None:
            ref.add_tags(("FITTED_TRANSFORMER",))


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
        ref = ValueRef(name=inner.var or dotted_text(inner_node) or "<call>",
                       scope=call.scope, tags=call_output_tags(inner, call.scope),
                       producer=inner, loc=inner.loc, class_ir=inner.class_ir)
        slot = slot_of(inner)
        if slot is not None:
            ref.via_fqns = slot.fqns
            ref.class_ir = ref.class_ir or slot.class_ir
        return ref
    if isinstance(inner_node, ast.Subscript):
        # `X = df[cols].to_numpy()` - the subscript preserves the frame's tags,
        # but it is not a name, so there is no binding to look up.
        base = binding_of(dotted_text(inner_node.value), call.scope)
        if base is None:
            return None
        return ValueRef(name=base.name, scope=call.scope, tags=base.tags,
                        producer=base.producer, loc=base.loc,
                        class_ir=base.class_ir, via_fqns=base.via_fqns)
    return None


def _attribute_callable(receiver_name: str, method: str,
                        scope: ScopeIR) -> Optional[ValueRef]:
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
    ref = binding_of("%s.%s" % (receiver_name, method), scope)
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

    # 3. a method / call on a bound value
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
        held = _attribute_callable(receiver_name, method, call.scope)
        if held is not None:
            call.receiver_name = "%s.%s" % (receiver_name, method)
            ref, method = held, "__call__"
        else:
            ref = binding_of(receiver_name, call.scope)
    elif method is None:
        return
    if ref is None and receiver_name == "self":
        attr_ref = binding_of("self.%s" % method, call.scope)
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
    """`model(x)` on an nn.Module instance is a forward pass."""
    if call.method == "__call__" and call.class_ir is not None and call.class_ir.is_nn_module:
        if "torch.nn.Module.__call__" not in call.canonical_fqns:
            call.canonical_fqns = call.canonical_fqns + ("torch.nn.Module.__call__",)
