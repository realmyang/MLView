"""Flow-insensitive binding tracking.

Every assignment, tuple unpacking, `with ... as`, `for` target, walrus and
`self.x` attribute becomes a `ValueRef` carrying the `ValueTag`s that dataflow
(never a name regex alone) established. `call_output_tags` decides what a call
hands back, including one level of in-workspace return-type inference
(`ir/returns.py`) and the pandas frame pass-through.

The other direction - `obj.m(...)` -> the canonical FQNs it answers to - lives
in `ir/resolve.py`, which imports from here.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .. import knowledge as K
from .model import CallSite, ModuleIR, ScopeIR, ValueRef, sort_tags
from .returns import slot_of
from .scopes import AssignRecord, literal_str
from .symbols import dotted_text

__all__ = ["binding_of", "bind_module", "call_output_tags", "names_in",
           "identity_receiver", "CONFIG_NAME_RE", "IDENTITY_METHODS", "TENSOR_ROLES"]

CONFIG_NAME_RE = re.compile(r"(?i)^(cfg|config|args|opts|options|hparams|params|settings)$")
_TEST_NAME_RE = re.compile(r"(?i)^(x|y)?_?(test|holdout)")
_VAL_NAME_RE = re.compile(r"(?i)^(x|y)?_?(val|valid|validation|dev)")
_TRAIN_NAME_RE = re.compile(r"(?i)^(x|y)?_?train")
_TARGET_NAME_RE = re.compile(r"(?i)^(y|target|labels?|classes)([_0-9].*)?$")
_FEATURE_NAME_RE = re.compile(r"(?i)^(x|features?|inputs?|data)([_0-9].*)?$")

# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def binding_of(name: Optional[str], scope: Optional[ScopeIR],
               at: Optional[int] = None, in_loop: bool = False) -> Optional[ValueRef]:
    """The `ValueRef` a name resolves to, walking the scope chain outwards.

    With `at` (the 1-based line of the *consumer*) the name is resolved against
    the store in effect at that line rather than against the last store in the
    scope - REV-01. `bindings` is a flat `name -> one ValueRef` map, so a
    rebound name kept only its last producer, and `x = self.pool(x)` at line 42
    was handed to the consumer `self.stem(x)` at line 39: the shipped demo drew
    `self.pool -> self.stem`, one of four forward edges pointing backwards, and
    the real `relu -> self.pool` edge missing.

    The ordered lookup applies only to the consumer's **own** scope, and never
    to a class scope: a `self.x` store lives in the class scope and is read
    from methods that run in any order, so statement order says nothing there.
    When a name has several stores in that scope and none precedes the
    consumer, the value is a parameter (or a previous iteration): inside a loop
    the last store is the honest answer, and outside one the name is local and
    unwritten, so nothing is returned rather than an outer scope's value.
    """
    if not name or scope is None:
        return None
    cur: Optional[ScopeIR] = scope
    first = True
    while cur is not None:
        if first and at is not None and cur.kind != "class":
            history = cur.binding_history.get(name)
            if history is not None and len(history) > 1:
                picked = _store_before(history, at)
                if picked is not None:
                    return picked
                return cur.bindings.get(name) if in_loop else None
        ref = cur.bindings.get(name)
        if ref is not None:
            return ref
        cur = cur.parent
        first = False
    return None


def _store_before(history: Sequence[ValueRef], line: int) -> Optional[ValueRef]:
    """The last store written strictly above `line`, else None.

    Strictly above, because the right-hand side of `x = f(x)` is evaluated
    before the name is rebound: the consumer on that line reads the *previous*
    value, which is exactly the edge the flat map inverted.
    """
    picked: Optional[ValueRef] = None
    for ref in history:
        loc = ref.loc
        if loc is None or loc.line >= line:
            continue
        picked = ref
    return picked


def _class_scope(scope: ScopeIR) -> Optional[ScopeIR]:
    cur: Optional[ScopeIR] = scope
    while cur is not None:
        if cur.kind == "class":
            return cur
        cur = cur.parent
    return None


def _store(scope: ScopeIR, name: str, ref: ValueRef) -> None:
    target = scope
    if name.startswith("self."):
        target = _class_scope(scope) or scope
    ref.scope = target
    target.bindings[name] = ref
    # REV-01: the ordered record, appended in the source order `bind_module`
    # walks `module.assignments` in. `bindings` keeps its last-wins meaning, so
    # every caller that does not pass a consumer line is byte-for-byte
    # unchanged.
    target.binding_history.setdefault(name, []).append(ref)


def names_in(node: Optional[ast.AST]) -> Tuple[str, ...]:
    """Every name / dotted name read by an expression, in source order."""
    if node is None:
        return ()
    out: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            text = dotted_text(child)
            if text and text not in out:
                out.append(text)
        elif isinstance(child, ast.Name):
            if child.id not in out:
                out.append(child.id)
    return tuple(out)


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

#: Roles whose result is a torch tensor rather than an object of its own class.
TENSOR_ROLES = frozenset({"FORWARD", "LOSS_FN", "SCALE", "ARGMAX", "ITEM", "DETACH",
                          "TO_DEVICE", "TO_NUMPY"})

#: `nn.Module` methods that return `self`. `model = Net().to(device)` is the
#: canonical PyTorch idiom, and the value it binds is still a `Net` - dropping
#: the class here is what made MLV301 unable to see the model's layers.
IDENTITY_METHODS = frozenset({"to", "cuda", "cpu", "npu", "xpu", "mps", "float",
                              "half", "double", "bfloat16", "eval", "train",
                              "requires_grad_", "share_memory"})


def identity_receiver(call: Optional[CallSite]) -> Optional["ValueRef"]:
    """The receiver of an identity-preserving method call, else None."""
    if call is None or call.receiver is None:
        return None
    if (call.method or "") not in IDENTITY_METHODS:
        return None
    return call.receiver


#: Attributes that hand back *another estimator*. `best = search.best_estimator_`
#: has to keep the sklearn family, or the receiver resolver falls back on the
#: MODEL tag alone and proposes `torch.nn.Module.predict` for it.
ESTIMATOR_ATTRS = ("best_estimator_", "best_model_", "_final_estimator",
                   "final_estimator_", "estimator_", "regressor_", "classifier_",
                   "named_steps", "steps")


def _estimator_attr_base(value: Optional[ast.AST]) -> Optional[str]:
    """`search.best_estimator_` / `pipe.named_steps["clf"]` -> the base name."""
    node = value
    if isinstance(node, ast.Subscript):
        node = node.value
    if not isinstance(node, ast.Attribute) or node.attr not in ESTIMATOR_ATTRS:
        return None
    return dotted_text(node.value)


def _first_arg_tags(call: CallSite, scope: ScopeIR) -> Tuple[str, ...]:
    if not call.args:
        return ()
    ref = binding_of(dotted_text(call.args[0]), scope)
    return tuple(ref.tags) if ref else ()


def call_output_tags(call: CallSite, scope: ScopeIR) -> Tuple[str, ...]:
    """The `ValueTag`s of the value a call produces."""
    fqns = list(call.canonical_fqns) or ([call.fqn] if call.fqn else [])
    entry, _fqn = K.best_entry(fqns)
    role = entry["role"] if entry else None
    tags = list(entry["tags"]) if entry else []

    if call.class_ir is not None:
        if call.class_ir.is_nn_module:
            tags.append("MODEL")
        elif "torch.utils.data.Dataset" in call.class_ir.resolved_bases:
            tags.append("RAW_DATA")

    if entry is None and call.target_function is not None:
        slot = slot_of(call)
        if slot is not None:
            tags.extend(slot.tags)

    receiver = call.receiver
    if role == "FRAME_OP" and receiver is not None:
        # `X = df.drop(columns=[target])` / `.copy()` / `.to_numpy()` keeps the
        # RAW_DATA / FEATURES / TARGET tags `pandas.read_csv` seeded: dropping
        # them on the first hop is what made MLV101 blind to the pandas path.
        tags.extend(receiver.tags)
    elif role in ("FIT_TRANSFORM", "TRANSFORM"):
        inherited = [t for t in _first_arg_tags(call, scope) if t != "FITTED_TRANSFORMER"]
        tags.extend(inherited)
        if not inherited:
            tags.append("FEATURES")
    elif role == "FORWARD":
        if receiver is not None and receiver.has("LOSS"):
            tags = ["LOSS"]
        elif receiver is not None and receiver.has("MODEL"):
            tags.append("LOGITS")
    elif role in ("LOSS_CLS", "LOSS_FN"):
        tags.append("LOSS")
    elif role == "TO_DEVICE" and receiver is not None:
        tags.extend(t for t in receiver.tags if t != "DEVICE")
    elif role in ("ITEM", "DETACH", "TO_NUMPY") and receiver is not None:
        tags.extend(receiver.tags)
    elif role == "ARGMAX":
        tags.append("PREDS")
    elif role == "SPLIT" and not tags:
        tags.extend(_first_arg_tags(call, scope))
    return sort_tags(tags)


def _reinforce(name: str, tags: Sequence[str]) -> Tuple[str, ...]:
    """Name regexes may only *reinforce* a tag dataflow already established."""
    out = list(tags)
    has_data = any(t in out for t in ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT",
                                      "VAL_SPLIT", "TEST_SPLIT", "BATCH", "LOADER"))
    if not has_data:
        return tuple(out)
    short = name.split(".")[-1]
    if _TEST_NAME_RE.match(short) and "TRAIN_SPLIT" not in out:
        out.append("TEST_SPLIT")
    elif _VAL_NAME_RE.match(short) and "TRAIN_SPLIT" not in out:
        out.append("VAL_SPLIT")
    elif _TRAIN_NAME_RE.match(short):
        out.append("TRAIN_SPLIT")
    if _TARGET_NAME_RE.match(short):
        out = [t for t in out if t != "FEATURES"] + ["TARGET"]
    elif _FEATURE_NAME_RE.match(short):
        out = [t for t in out if t != "TARGET"] + ["FEATURES"]
    return tuple(out)


def _split_positions(call: CallSite, count: int) -> List[Tuple[str, ...]]:
    """Positional tag convention for split-producing calls."""
    fqn = call.fqn or ""
    if fqn.endswith("train_test_split"):
        if count == 4:
            return [("FEATURES", "TRAIN_SPLIT"), ("FEATURES", "TEST_SPLIT"),
                    ("TARGET", "TRAIN_SPLIT"), ("TARGET", "TEST_SPLIT")]
        if count == 2:
            return [("TRAIN_SPLIT",), ("TEST_SPLIT",)]
        if count == 6:
            return [("FEATURES", "TRAIN_SPLIT"), ("FEATURES", "VAL_SPLIT"),
                    ("FEATURES", "TEST_SPLIT"), ("TARGET", "TRAIN_SPLIT"),
                    ("TARGET", "VAL_SPLIT"), ("TARGET", "TEST_SPLIT")]
    if fqn.endswith("random_split"):
        if count == 2:
            return [("TRAIN_SPLIT", "RAW_DATA"), ("VAL_SPLIT", "RAW_DATA")]
        if count == 3:
            return [("TRAIN_SPLIT", "RAW_DATA"), ("VAL_SPLIT", "RAW_DATA"),
                    ("TEST_SPLIT", "RAW_DATA")]
    role = K.role_of(fqn)
    if role == "DATASET" and count == 2:
        return [("RAW_DATA", "FEATURES"), ("RAW_DATA", "TARGET")]
    return []


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
        ref = ValueRef(name="self", scope=cls.scope, tags=("MODEL",) if cls.is_nn_module else (),
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
        if call is not None:
            tags.extend(call_output_tags(call, scope))
            class_ir = call.class_ir or _identity_class(call)
            role = K.role_of(call.fqn)
            if role in ("CONFIG_LOAD", "CONFIG_ENV", "HF_ARGS"):
                is_config = True
            if call.var is None:
                call.var = name
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
        _store(scope, name, ref)


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


