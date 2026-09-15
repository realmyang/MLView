"""The three cross-call passes that need the resolver's machinery.

  * `seed_annotations`     a parameter's type annotation resolves to a class in
                           the workspace, so `def train(model: SmallCNN)` binds
                           `model` before any call is seen.
  * `propagate_parameters` one level of argument -> parameter: what the caller
                           passed becomes what the callee's parameter holds.
  * `mark_fitted`          a transformer that has been `fit` is marked, so the
                           leakage rules can tell fitting from transforming.

They live beside the resolver rather than inside it because each is a whole
walk of its own, and none of them is on the path that resolves a single call.
"""

from __future__ import annotations

import ast
from typing import Optional

from .. import knowledge as K
from .bindings import binding_of, call_output_tags
from .model import CallSite, ClassIR, ModuleIR, ScopeIR, ValueRef, sort_tags
from .resolve_receivers import _local_lookup
from .returns import slot_of
from .symbols import dotted_text


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
            if ref is None:
                # NLP2-01. An argument written **inline** - `train(Net(),
                # loader)`, `to_device(build_model(), device)` - has no name to
                # look up, so the parameter stayed untyped and everything
                # downstream of it evaporated: `model(features)` inside the
                # callee resolved to nothing, no eval region was built, and
                # MLV301 (high) and MLV302 vanished on `hydra_research`,
                # `amp_accumulation` and every project that writes
                # `model = train(Net(), loader)`. The call site is already in
                # the IR; reading it costs one dict hit.
                inner = _inline_call(arg, module)
                if inner is not None:
                    ref = _value_of_call(inner, call.scope, param)
            if ref is None or not (ref.tags or ref.class_ir or ref.via_fqns
                                   or ref.entries or ref.elements):
                continue
            existing = func.scope.bindings.get(param)
            if existing is not None and (existing.tags or existing.class_ir
                                         or existing.via_fqns or existing.entries
                                         or existing.elements):
                continue
            func.scope.bindings[param] = ValueRef(
                name=param, scope=func.scope, tags=ref.tags, producer=ref.producer,
                loc=func.loc, class_ir=ref.class_ir, is_config=ref.is_config,
                via_fqns=ref.via_fqns, elements=ref.elements, entries=ref.entries)


def _inline_call(node, module: ModuleIR) -> Optional[CallSite]:
    """The `CallSite` for an argument written as a call expression."""
    if not isinstance(node, ast.Call):
        return None
    by_node = getattr(module, "_calls_by_node", None)
    if by_node is None:
        by_node = {id(c.node): c for c in module.calls}
    return by_node.get(id(node))


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
        # REC-04: `run(make_state(), loader())`. The container the callee
        # returns has to reach the parameter, or the whole point of the factory
        # is lost one line after it is written - `state["scaler"]` inside `run`
        # is then an opaque subscript and the GradScaler is invisible. The slots
        # were resolved in `make_state`'s own scope by `ir/returns`.
        ref.elements = slot.elements
        ref.entries = slot.entries
    return ref
