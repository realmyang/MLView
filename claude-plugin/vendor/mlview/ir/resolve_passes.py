"""The three cross-call passes that ride on receiver resolution.

Parameter annotations (`seed_annotations`), one level of argument -> parameter
summaries (`propagate_parameters`) and the fitted-transformer mark
(`mark_fitted`). Split out of `ir/resolve.py`, which re-exports all three.
"""

from __future__ import annotations

import ast
from typing import Optional

from .. import knowledge as K
from .bindings import binding_of
from .model import CallSite, ClassIR, ModuleIR, ScopeIR, ValueRef, sort_tags
from .resolve_receivers import _local_lookup
from .symbols import dotted_text

__all__ = ["seed_annotations", "propagate_parameters", "mark_fitted",
           "argument_value"]


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


def argument_value(site: CallSite, arg) -> Optional[ValueRef]:
    """The value one argument expression stands for, name **or construction**.

    GRAPH-R3. `train(Net(), loader)` is how a training entry point is written
    at least as often as `train(model, loader)`, and an inline construction has
    no name to look up - so every argument-to-parameter summary returned
    *nothing* for it, `train`'s `model` parameter stayed untyped, and the
    forward pass inside (and everything downstream of the function's return)
    was invisible. The construction states its own type; this reads it.

    Only a call that is already in the IR is read, so nothing is invented, and
    an argument that is neither a name nor a call still contributes nothing.
    """
    from .bindings import call_output_tags       # local: cyclic at import
    from .returns import slot_of

    if arg is None:
        return None
    if not isinstance(arg, ast.Call):
        # `dotted_text` answers for a call too - it returns the *callee's* name -
        # so the call case has to be taken first or `train(Net(), loader)` looks
        # up a binding called `Net`, finds none, and reports nothing.
        name = dotted_text(arg)
        return binding_of(name, site.scope, at=site.loc.line) if name else None
    inner = getattr(site.module, "_calls_by_node", {}).get(id(arg))
    if inner is None:
        return None
    ref = ValueRef(name=inner.var or inner.short_name, scope=site.scope,
                   tags=call_output_tags(inner, site.scope), producer=inner,
                   loc=inner.loc, class_ir=inner.class_ir)
    slot = slot_of(inner)
    if slot is not None:
        ref.via_fqns = slot.fqns
        ref.class_ir = ref.class_ir or slot.class_ir
    return ref


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
            ref = argument_value(call, arg)
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
