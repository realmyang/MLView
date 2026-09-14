"""The three cross-call passes that ride on receiver resolution.

Parameter annotations (`seed_annotations`), one level of argument -> parameter
summaries (`propagate_parameters`) and the fitted-transformer mark
(`mark_fitted`). Split out of `ir/resolve.py`, which re-exports all three.
"""

from __future__ import annotations

from typing import Optional

from .. import knowledge as K
from .bindings import binding_of
from .model import ClassIR, ModuleIR, ScopeIR, ValueRef, sort_tags
from .resolve_receivers import _local_lookup
from .symbols import dotted_text

__all__ = ["seed_annotations", "propagate_parameters", "mark_fitted"]


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
