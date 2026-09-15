"""The binding pass: every assignment record becomes a `ValueRef` in a scope.

Split out of `ir/bindings.py`, which re-exports everything here. Imports
`bindings_lookup` and `bindings_tags`; nothing imports this module back.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Tuple

from .. import knowledge as K
from .bindings_lookup import _store, binding_of, names_in
from .bindings_tags import (_estimator_attr_base, _reinforce, _split_positions,
                            call_output_tags, identity_receiver)
from .config_values import CONFIG_NAME_RE, resolve_module as _resolve_config
from .containers import (carried_element, element_expr, expr_value,
                         is_container, subscript_key)
from .model import CallSite, ModuleIR, ValueRef, sort_tags
from .returns import slot_of
from .scopes_records import AssignRecord, literal_str
from .symbols import dotted_text

__all__ = ["bind_module", "rebind_containers"]


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


def rebind_containers(module: ModuleIR, workspace) -> None:
    """REC-04: resolve `state["scaler"]` once `state` is known to be a container.

    `bind_module` clears and rebuilds every binding at the top of each IR round,
    so a parameter binding that `ir.summaries` wrote in round N is gone before
    round N+1 reads `scaler = state["scaler"]`. The tag propagation never
    noticed, because only *rules* read parameter tags - but the container read
    happens inside the binding pass itself, which is why the GradScaler carried
    in a parameter dict stayed invisible however far the summaries travelled.

    This pass runs straight after the summaries, in the same round, and only
    ever **upgrades**: a name whose binding already resolved to something keeps
    what it had, and a subscript that still resolves to nothing is left exactly
    as unresolved as it was - including its `opaque` note.
    """
    for record in module.assignments:
        if record.call is not None or not isinstance(record.value, ast.Subscript):
            continue
        for target in record.targets:
            name = dotted_text(target)
            if not name:
                continue
            ref = record.scope.bindings.get(name)
            if ref is None or ref.tags or ref.producer is not None \
                    or ref.class_ir is not None:
                continue
            carried = _carried_element(record.value, record.scope, module)
            if carried is None:
                continue
            ref.tags = sort_tags(tuple(_reinforce(name, list(carried.tags))))
            ref.producer = carried.producer
            ref.class_ir = carried.class_ir
            if not ref.via_fqns:
                ref.via_fqns = carried.via_fqns
            ref.opaque = None


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
        carried = (_carried_elements(value, scope, module) if call is None
                   else _prepared_elements(call, scope, module, len(names)))
        for index, name in enumerate(names):
            if not name:
                continue
            slot = slot_of(call, index) if call is not None else None
            element = (carried[index] if carried is not None and index < len(carried)
                       else None)
            if element is not None and call is not None:
                # GRAPH-R3: `model, opt, loader = accelerator.prepare(model, opt,
                # loader)` - position *i* of the result IS argument *i*, which
                # is what `prepare` and `Fabric.setup` document.
                tags = list(element.tags) + list(base_tags)
            elif index < len(positions):
                tags = list(positions[index])
            elif slot is not None:
                tags = list(slot.tags)
            elif element is not None:
                tags = list(element.tags)
            else:
                tags = list(base_tags)
            tags = list(_reinforce(name, tags))
            ref = ValueRef(name=name, scope=scope, tags=sort_tags(tags),
                           producer=call or (element.producer if element else None),
                           loc=record.loc, sources=sources, index=index)
            if call is not None:
                ref.class_ir = call.class_ir or _identity_class(call)
                if ref.class_ir is None and element is not None:
                    ref.class_ir = element.class_ir
                if not ref.via_fqns and element is not None:
                    ref.via_fqns = element.via_fqns
            elif element is not None:
                # GRAPH-R3: `opt_a, opt_b = optimizers`. The right-hand side is
                # a tuple the analyzer can see, so each name keeps the object
                # its own position carries instead of all of them keeping
                # nothing.
                ref.class_ir = element.class_ir
                ref.via_fqns = element.via_fqns
            if slot is not None:
                ref.via_fqns = slot.fqns
                ref.class_ir = ref.class_ir or slot.class_ir
                _carry_container(ref, slot)
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
        producer_override: Optional[CallSite] = None
        if call is not None:
            tags.extend(call_output_tags(call, scope))
            class_ir = call.class_ir or _identity_class(call) or _wrapped_class(call, scope)
            role = K.role_of(call.fqn)
            if role in ("CONFIG_LOAD", "CONFIG_ENV", "HF_ARGS"):
                is_config = True
            if call.var is None:
                call.var = name
        elif value is not None:
            carried = _carried_element(value, scope, module)
            if carried is not None:
                # GRAPH-R3: `scaler = ctx["scaler"]` out of a dict literal this
                # module builds. The object keeps its class, its producer and
                # its tags, so `scaler.scale(loss)` resolves the way it does
                # when the same GradScaler is held in a plain local.
                tags.extend(carried.tags)
                class_ir = carried.class_ir
                via = carried.via_fqns
                producer_override = carried.producer
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
        ref = ValueRef(name=name, scope=scope, tags=sort_tags(tags),
                       producer=call or producer_override,
                       loc=record.loc, sources=sources, literal=literal,
                       class_ir=class_ir, is_config=is_config)
        if is_container(value):
            # Remembered so a later `ctx["scaler"]` / `pair[0]` can be followed
            # back to the element that built it (`ir.containers`).
            ref.container = value
        slot = slot_of(call) if call is not None else None
        if slot is not None:
            ref.via_fqns = slot.fqns
            ref.class_ir = ref.class_ir or slot.class_ir
            _carry_container(ref, slot)
        if not ref.via_fqns:
            passthrough = identity_receiver(call)
            if passthrough is not None and passthrough.via_fqns:
                ref.via_fqns = passthrough.via_fqns
        if not ref.via_fqns and call is None and via:
            ref.via_fqns = tuple(via)
        if ref.class_ir is None and producer_override is not None:
            ref.class_ir = producer_override.class_ir
        # REC-04: a subscript the analyzer *did* follow into a container
        # literal is not an unresolved construct; saying it is made a resolved
        # object report itself as a gap.
        ref.opaque = (None if producer_override is not None or class_ir is not None
                      else _opaque_kind(value, call, record))
        _store(scope, name, ref)
        _bind_construction_attrs(call, name, scope, module)


#: ANA-5a. Value expressions whose product the analyzer cannot follow, named so
#: that a call *through* the binding can say which construct defeated it. Only
#: bindings that really exist are described: iron law 1 is unchanged, this
#: invents no FQN and asserts nothing about what the value is.
def _opaque_kind(value, call: Optional[CallSite], record: AssignRecord) -> Optional[str]:
    if call is not None:
        if call.short_name == "field" and "default_factory" in call.kwarg_nodes:
            return "a dataclass default_factory"
        return None
    if isinstance(value, ast.Lambda):
        return "a lambda"
    if record.in_match:
        return "a value assigned in a match case"
    if isinstance(value, ast.IfExp):
        return "a conditional expression"
    if isinstance(value, ast.Subscript):
        return "a subscript"
    return None


#: Roles whose call hands back the object it was given, rebound.
_REBIND_ROLES = ("WRAP_PREPARE", "WRAP_MODEL")


def _wrapped_class(call: Optional[CallSite], scope) -> Optional[object]:
    """`model = accelerator.prepare(model)` keeps `model`'s workspace class.

    `torch.compile`, `DistributedDataParallel`, `Accelerator.prepare` and
    `Fabric.setup` all return the same object under a wrapper, and the entry
    row's MODEL tag alone is not the identity: without the class, `model(x)`
    one line later stopped resolving to the workspace `forward` and the whole
    step after the wrapper went quiet.
    """
    if call is None or K.role_of(call.fqn) not in _REBIND_ROLES or not call.args:
        return None
    value = expr_value(call.args[0], scope, call.module, at=call.loc.line)
    return value.class_ir if value is not None else None


def _prepared_elements(call: Optional[CallSite], scope, module,
                       count: int) -> Optional[List[Optional[ValueRef]]]:
    """Positional identity for a rebinding wrapper, when the arity matches."""
    if (call is None or K.role_of(call.fqn) not in _REBIND_ROLES
            or len(call.args) != count or count < 2):
        return None
    return [expr_value(arg, scope, module, at=call.loc.line) for arg in call.args]


def _construct_fields(cls) -> Tuple[str, ...]:
    """The positional field names of a workspace class construction.

    `__init__`'s parameters when the class writes one, and the **annotated
    class-body fields** when it does not - which is exactly the `@dataclass`
    case, where the constructor is generated and there is no `__init__` in the
    source to read.
    """
    init = (cls.methods or {}).get("__init__")
    if init is not None:
        params = list(init.params)
        return tuple(params[1:] if params and params[0] == "self" else params)
    out = []
    for stmt in getattr(cls.node, "body", ()) or ():
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            out.append(stmt.target.id)
    return tuple(out)


def _bind_construction_attrs(call: Optional[CallSite], name: str, scope, module) -> None:
    """GRAPH-R3: `bundle = Bundle(model=model, optimizer=opt)` binds
    `bundle.model` and `bundle.optimizer` in the **caller's** scope.

    A dataclass (or any small holder class) is how a script carries its objects
    from one function to the next, and its fields were names nothing bound:
    `bundle.model(x)` drew no node and `bundle.optimizer.step()` resolved to no
    symbol. Only a **workspace class** is followed, only a field the
    constructor really names, and only a value that is itself something -
    a tagged value, a workspace class or a resolved call - so no FQN is
    invented and a `Bundle(path="runs")` binds nothing.
    """
    cls = call.class_ir if call is not None else None
    if cls is None or not name or "." in name:
        return
    fields = _construct_fields(cls)
    if not fields:
        return
    pairs = {}
    for index, arg in enumerate(call.args):
        if index < len(fields):
            pairs[fields[index]] = arg
    for key in sorted(call.kwarg_nodes):
        if key in fields:
            pairs[key] = call.kwarg_nodes[key]
    for field in sorted(pairs):
        value = expr_value(pairs[field], scope, module, at=call.loc.line)
        if value is None or not (value.tags or value.class_ir or value.producer):
            continue
        _store(scope, "%s.%s" % (name, field),
               ValueRef(name="%s.%s" % (name, field), scope=scope,
                        tags=value.tags, producer=value.producer,
                        loc=call.loc, class_ir=value.class_ir,
                        via_fqns=value.via_fqns))


def _carry_container(ref: ValueRef, slot) -> None:
    """REC-04: `state = make_state()` keeps the literal the factory returned.

    Only when the name has no container of its own - a real literal on the
    right-hand side always wins - and only with the scope the elements have to
    be read in, so nothing here can make a name in one scope stand for a name
    in another.
    """
    holder = getattr(slot, "container", None)
    if holder is None or ref.container is not None:
        return
    ref.container = holder
    ref.container_scope = getattr(slot, "container_scope", None)
    ref.container_module = getattr(slot, "container_module", None)


def _carried_element(value, scope, module) -> Optional[ValueRef]:
    """`ctx["scaler"]` / `pair[0]` -> the element of the literal behind it."""
    if not isinstance(value, ast.Subscript):
        return None
    key = subscript_key(value)
    if key is None:
        return None
    base = binding_of(dotted_text(value.value), scope)
    return carried_element(base, key, scope, module)


def _carried_elements(value, scope, module) -> Optional[List[Optional[ValueRef]]]:
    """`a, b = pair` -> one `ValueRef` per position of the tuple behind `pair`."""
    node = value
    base = None
    if not is_container(node):
        name = dotted_text(node) if node is not None else None
        base = binding_of(name, scope) if name else None
        node = base.container if base is not None else None
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    home = (base.container_scope or scope) if base is not None else scope
    home_module = (base.container_module if base is not None
                   and base.container_scope is not None else module)
    return [expr_value(elt, home, home_module) for elt in node.elts]


def _identity_class(call: Optional[CallSite]):
    """`Net().to(device)` / `model.cuda()` keeps the receiver's workspace class."""
    ref = identity_receiver(call)
    return ref.class_ir if ref is not None else None


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
