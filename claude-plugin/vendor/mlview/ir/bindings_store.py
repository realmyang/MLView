"""The binding pass: every assignment record becomes a `ValueRef` in its scope.

`bind_module` is the entry point `ir/build_ir.py` calls each round - imported
values first, then `self` parameters, then every `AssignRecord` the scope walk
recorded, in source order - and `rebind_projections` is the second, narrower
pass that re-runs only the records whose right-hand side projects a container,
once the container's own tags have converged.

`_bind_record` is where a single assignment turns into bindings: it asks
`ir/bindings_values.py` what the right-hand side evaluates to, `ir/bindings_tags.py`
what a call hands back, and `ir/bindings_lookup._store` to write the result.
"""
from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .. import knowledge as K
from .bindings_lookup import _REBINDING, _store, binding_of, names_in
from .bindings_tags import (_estimator_attr_base, _reinforce,
                            _split_positions, call_output_tags,
                            identity_receiver)
from .bindings_values import (_PROJECTION_TAGS, _adopt, _identity_class,
                              _literal_elements, _literal_entries,
                              _opaque_kind, _restored_into, _self_wrapped,
                              _subscript_base, _subscript_slot, _trim_via)
from .config_values import CONFIG_NAME_RE, resolve_module as _resolve_config
from .model import ModuleIR, ValueRef, sort_tags
from .returns import slot_of
from .scopes import AssignRecord, literal_str
from .symbols import dotted_text

__all__ = ["bind_module", "rebind_projections"]


# ---------------------------------------------------------------------------
# binding pass
# ---------------------------------------------------------------------------

def bind_module(module: ModuleIR, workspace) -> None:
    """(Re)build every binding in a module from its assignment records."""
    for scope in module.scopes:
        scope.bindings.clear()
        scope.binding_history.clear()
    for record in module.assignments:
        try:
            _bind_record(record, module, workspace)
        except RecursionError:  # pragma: no cover - defensive
            continue
    _bind_self_params(module)
    _bind_imported_values(module, workspace)
    # ANA-10: config containers are resolved last, because every source it
    # reads - a dict literal, a dataclass construction, `parse_args()` - is a
    # binding this pass has just written, and because the leaves it stores must
    # never win over a real assignment to the same dotted name.
    _resolve_config(module, workspace)


def rebind_projections(module: ModuleIR, workspace) -> None:
    """Re-read the statements that project out of a **parameter** container.

    VIS2-06 / VIS2-08 / DGRG2-03. `bind_module` clears every binding and
    rebuilds from the statements, so the parameter bindings the cross-call
    passes write (`ir/resolve.propagate_parameters`, and `ir/summaries` under
    `--dataflow ip`) do not exist while the statements are being read. A
    statement whose meaning depends on one - and

        g_optimizer, d_optimizer = optimizers["g"], optimizers["d"]
        adversarial, pixel = criteria["adversarial"], criteria["pixel"]

    is exactly that, the layout every GAN, multi-loss detector and
    multi-optimizer RL trainer uses - could therefore never see it, however
    many rounds ran: `criterion(...)` resolved to nothing and MLV402 (high /
    0.95 on a `BCELoss` fed raw logits), MLV205 and the whole MLV2xx family
    went silent.

    This runs **after** the parameter passes, inside the same round and before
    `resolve_calls`, and it touches only the records whose right-hand side is a
    subscript - so nothing else is re-derived and the fixed point is unmoved.
    """
    _REBINDING["active"] = True
    try:
        for record in module.assignments:
            if record.call is not None or not _projects_a_container(record.value):
                continue
            try:
                _bind_record(record, module, workspace)
            except RecursionError:  # pragma: no cover - defensive
                continue
    finally:
        _REBINDING["active"] = False


def _projects_a_container(value) -> bool:
    if isinstance(value, ast.Subscript):
        return True
    if isinstance(value, (ast.Tuple, ast.List)):
        return any(isinstance(e, ast.Subscript) for e in value.elts)
    return False


def _bind_imported_values(module: ModuleIR, workspace) -> None:
    """`from data import train_loader` -> the ValueRef `data.py` bound for it.

    Importing a module-level *value* from another workspace module is how a
    real project hands a DataLoader to its training script. Without this the
    loop's `consumes` port is empty, the LOADER / TRAIN_SPLIT tags never reach
    it, and the Data lane has no edge into Train at all.
    """
    symbols = getattr(module, "symbols", None)
    scope = module.module_scope
    if symbols is None or scope is None or workspace is None:
        return
    for local in sorted(symbols.aliases):
        fqn = symbols.aliases[local]
        head, _dot, attr = fqn.rpartition(".")
        if not head or not attr:
            continue
        other = workspace.by_dotted.get(head)
        if other is None or other is module or other.module_scope is None:
            continue
        source = other.module_scope.bindings.get(attr)
        if source is None or source.producer is None:
            continue
        if local in scope.bindings:
            continue                 # a local assignment always wins
        scope.bindings[local] = ValueRef(
            name=local, scope=scope, tags=source.tags, producer=source.producer,
            loc=source.loc, sources=source.sources, literal=source.literal,
            class_ir=source.class_ir, is_config=source.is_config,
            via_fqns=source.via_fqns)


def _bind_self_params(module: ModuleIR) -> None:
    """Give every method's `self` a ValueRef pointing at its own class."""
    for cls in module.classes.values():
        ref = ValueRef(name="self", scope=cls.scope,
                       tags=("MODEL",) if cls.is_model_module else (),
                       loc=cls.loc, class_ir=cls)
        cls.scope.bindings.setdefault("self", ref)


def _bind_record(record: AssignRecord, module: ModuleIR, workspace) -> None:
    scope = record.scope
    value = record.value
    call = record.call
    sources = names_in(value)
    literal = literal_str(value)

    if record.kind == "for":
        _bind_for(record, module)
        return

    targets = record.targets
    # tuple unpacking
    flat = targets[0] if len(targets) == 1 else None
    if isinstance(flat, (ast.Tuple, ast.List)):
        elts = [e for e in flat.elts]
        names = [dotted_text(e) for e in elts]
        positions = _split_positions(call, len(names)) if call else []
        base_tags = call_output_tags(call, scope) if call else ()
        # ROB-15 / DGRG2-03. Where the slots are *known* - the right-hand side
        # is a tuple/list literal of the same arity, or a name already bound to
        # one - each target takes its own element's type rather than the whole
        # statement's. `opt, crit = Adam(...), CrossEntropyLoss()` is plain
        # parallel assignment and needs no inference; without it both names were
        # stored with no tags and no producer, `opt.zero_grad()` /
        # `loss.backward()` drew nothing, and the training loop was relabelled
        # an eval loop on a file with no evaluation in it.
        per_slot = _literal_elements(value, scope, module)
        if len(per_slot) != len(names):
            per_slot = ()
        if not per_slot and call is None and value is not None:
            source_ref = binding_of(dotted_text(value), scope)
            if source_ref is not None and len(source_ref.elements) == len(names):
                per_slot = source_ref.elements
        for index, name in enumerate(names):
            if not name:
                continue
            slot = slot_of(call, index) if call is not None else None
            if index < len(positions):
                tags = list(positions[index])
            elif slot is not None:
                tags = list(slot.tags)
            else:
                tags = list(base_tags)
            tags = list(_reinforce(name, tags))
            ref = ValueRef(name=name, scope=scope, tags=sort_tags(tags), producer=call,
                           loc=record.loc, sources=sources, index=index)
            if call is not None:
                ref.class_ir = call.class_ir or _identity_class(call)
            if slot is not None:
                ref.via_fqns = slot.fqns
                ref.class_ir = ref.class_ir or slot.class_ir
            if per_slot:
                _adopt(ref, per_slot[index])
            elif call is not None:
                _adopt(ref, _self_wrapped(call, name, scope))
            _store(scope, name, ref)
        return

    for target in targets:
        name = dotted_text(target)
        if not name:
            continue
        if record.kind == "aug":
            existing = binding_of(name, scope)
            tags = list(existing.tags) if existing else []
            tags.extend(call_output_tags(call, scope) if call else ())
            for src in sources:
                ref_src = binding_of(src, scope)
                if ref_src is not None:
                    tags.extend(ref_src.tags)
            ref = ValueRef(name=name, scope=scope, tags=sort_tags(tags),
                           producer=call or (existing.producer if existing else None),
                           loc=record.loc, sources=sources)
            _store(scope, name, ref)
            continue

        tags: List[str] = []
        class_ir = None
        is_config = False
        via: Tuple[str, ...] = ()
        picked: Optional[ValueRef] = None
        if call is not None:
            tags.extend(call_output_tags(call, scope))
            class_ir = call.class_ir or _identity_class(call)
            role = K.role_of(call.fqn)
            if role in ("CONFIG_LOAD", "CONFIG_ENV", "HF_ARGS"):
                is_config = True
            if call.var is None:
                call.var = name
        elif _subscript_slot(value, scope, module) is not None:
            # VIS2-06 / VIS2-08: a literal container read by a constant key.
            picked = _subscript_slot(value, scope, module)
            tags.extend(picked.tags)
            class_ir = picked.class_ir
            via = picked.via_fqns or (
                _trim_via(picked.producer.canonical_fqns)
                if picked.producer is not None else ())
        elif isinstance(value, ast.Subscript):
            # NLP-02. `ir/resolve._chained_receiver` models the subscript hop
            # when it is written inside the receiver expression
            # (`enc["train"].train_test_split(...)`), which is the shape
            # `knowledge/hf_tbl.py` was written for. The equally common shape
            # captures it into a binding first - `raw = load_dataset(...)
            # ["train"]` - and everything downstream evaporated: `raw.map(...)`
            # and `encoded.train_test_split(...)` produced no nodes at all,
            # MLV601/MLV602 went quiet, and NO diagnostic was emitted. A
            # projection out of a container does not change what the rows are,
            # which is the same argument `_FRAME_OP` already makes for
            # `df.drop(columns=...)`; the family and the data tags travel, at
            # the same weight, and nothing else does.
            base_ref, base_call = _subscript_base(value, scope, module)
            tags.extend(t for t in (base_ref.tags if base_ref is not None else ())
                        if t in _PROJECTION_TAGS)
            if base_call is not None:
                tags.extend(t for t in call_output_tags(base_call, scope)
                            if t in _PROJECTION_TAGS)
                via = _trim_via(base_call.canonical_fqns)
                class_ir = base_call.class_ir
            if base_ref is not None and not via:
                via = base_ref.via_fqns or (
                    _trim_via(base_ref.producer.canonical_fqns)
                    if base_ref.producer is not None else ())
                class_ir = class_ir or base_ref.class_ir
        elif value is not None:
            base_name = _estimator_attr_base(value)
            base_ref = binding_of(base_name, scope) if base_name else None
            if base_ref is not None:
                tags.extend(t for t in base_ref.tags if t != "FITTED_TRANSFORMER")
                class_ir = base_ref.class_ir
                via = base_ref.via_fqns or (
                    base_ref.producer.canonical_fqns if base_ref.producer else ())
            else:
                via = ()
                for src in sources:
                    src_ref = binding_of(src, scope)
                    if src_ref is not None:
                        tags.extend(t for t in src_ref.tags
                                    if t not in ("FITTED_TRANSFORMER", "OPTIMIZER"))
                        break
        if isinstance(value, ast.Dict) and CONFIG_NAME_RE.match(name.split(".")[-1] or ""):
            is_config = True
        tags = list(_reinforce(name, tags))
        ref = ValueRef(name=name, scope=scope, tags=sort_tags(tags), producer=call,
                       loc=record.loc, sources=sources, literal=literal,
                       class_ir=class_ir, is_config=is_config)
        slot = slot_of(call) if call is not None else None
        if slot is not None:
            ref.via_fqns = slot.fqns
            ref.class_ir = ref.class_ir or slot.class_ir
        if not ref.via_fqns:
            passthrough = identity_receiver(call)
            if passthrough is not None and passthrough.via_fqns:
                ref.via_fqns = passthrough.via_fqns
        if not ref.via_fqns and call is None and via:
            ref.via_fqns = tuple(via)
        if call is not None:
            # INFRA-R2-04 / ROB-16 / DGRG2-01: keep what is already known when
            # the rebinding is a wrapper we have no row for, or a checkpoint
            # restored into a name that already held a model.
            _adopt(ref, _self_wrapped(call, name, scope)
                   or _restored_into(call, name, scope))
        if picked is not None:
            # REV-PREC-03. The slot's *producer* is the call that made the
            # value - `GradScaler()`, `nn.Linear(4, 3)` - and copying only its
            # tags left `scaler = parts["scaler"]` with no producer at all.
            # MLV208's identity arm (`_scaler_behind`) walks exactly that
            # producer to find the construction inside the factory, so a
            # GradScaler handed over in a parameter dict was invisible while
            # the same GradScaler handed over in a tuple was not: `opt, scaler
            # = build(model)` fired and `parts = build(); scaler =
            # parts["scaler"]` did not. `_adopt` is the same carriage the tuple
            # path above already uses, and it keeps whatever this binding
            # already knows.
            _adopt(ref, picked)
        ref.elements = _literal_elements(value, scope, module) or ref.elements
        ref.entries = _literal_entries(value, scope, module) or ref.entries
        if not ref.elements and not ref.entries and slot is not None:
            # REC-04: `state = make_state()` where the callee returns a dict
            # literal. The slots were resolved in the callee's scope by
            # `ir/returns`, so `state["scaler"]` reads an object rather than an
            # opaque subscript - the shape GRAPH-R3's carriage stopped at.
            ref.elements = slot.elements
            ref.entries = slot.entries
        # §5.3 A12': "a subscript the analyzer **did** follow into a literal
        # is no longer marked `opaque` - a resolved object must not report
        # itself as a gap." `picked` is that resolution.
        ref.opaque = None if picked is not None else _opaque_kind(
            value, call, record)
        _store(scope, name, ref)


def _bind_for(record: AssignRecord, module: ModuleIR) -> None:
    """`for images, labels in train_loader:` -> batch-tagged targets."""
    scope = record.scope
    iter_node = record.value
    target = record.targets[0]
    drop_first = False
    node = iter_node
    while isinstance(node, ast.Call):
        callee = node.func
        name = callee.attr if isinstance(callee, ast.Attribute) else (
            callee.id if isinstance(callee, ast.Name) else "")
        if name in ("enumerate", "tqdm", "trange", "iter", "list", "reversed"):
            if name == "enumerate":
                drop_first = True
            node = node.args[0] if node.args else None
            continue
        break
    source_ref = binding_of(dotted_text(node) if node is not None else None, scope)
    inherited = []
    if source_ref is not None:
        if source_ref.has("LOADER"):
            inherited.append("BATCH")
        inherited.extend(t for t in source_ref.tags
                         if t in ("TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT", "RAW_DATA"))

    elts: List[ast.expr]
    if isinstance(target, (ast.Tuple, ast.List)):
        elts = list(target.elts)
    else:
        elts = [target]
    if drop_first and len(elts) > 1:
        first = elts[0]
        name = dotted_text(first)
        if name:
            _store(scope, name, ValueRef(name=name, scope=scope, tags=(), loc=record.loc))
        elts = elts[1:]
        if len(elts) == 1 and isinstance(elts[0], (ast.Tuple, ast.List)):
            elts = list(elts[0].elts)

    for index, elt in enumerate(elts):
        name = dotted_text(elt)
        if not name:
            continue
        tags = list(inherited)
        if len(elts) > 1 and inherited:
            tags.append("FEATURES" if index == 0 else "TARGET")
        tags = list(_reinforce(name, tags))
        _store(scope, name, ValueRef(name=name, scope=scope, tags=sort_tags(tags),
                                     loc=record.loc, sources=names_in(iter_node),
                                     index=index))


