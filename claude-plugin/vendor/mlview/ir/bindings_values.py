"""What an *expression* evaluates to, for the binding pass to write down.

One layer above `ir/bindings_tags.py`, which answers only for a call: these
helpers answer for any right-hand side - a name, a literal tuple/list/dict and
its slots, a subscript into a container, a value a helper wrapped and handed
back (`x = f(..., x, ...)`), a model restored from a checkpoint - and hand back
the `ValueRef` the binding should adopt, `_adopt` preserving the provenance the
source value carried.

`ir/bindings_store.py` is the only caller; `ir/returns.py` reads
`_PROJECTION_TAGS` and `_subscript_base` through the `ir/bindings.py` shim.
"""
from __future__ import annotations

import ast
from typing import Optional, Tuple

from .. import knowledge as K
from .bindings_lookup import binding_of
from .bindings_tags import call_output_tags, identity_receiver
from .model import CallSite, ModuleIR, ScopeIR, ValueRef, sort_tags
from .returns import slot_of
from .scopes import AssignRecord, literal_str
from .symbols import dotted_text


#: ROB-15 / DGRG2-03 / VIS2-06. A tuple, list or dict **literal** is the one
#: container whose slots are known exactly, with no inference: the expression in
#: slot *i* is the value in slot *i*. Everything below reads those three shapes
#: and nothing else - a comprehension, a `dict(...)` call or a name are all left
#: alone, so this can never invent a slot that is not written in the source.

def _calls_by_node(module: ModuleIR):
    by_node = getattr(module, "_calls_by_node", None)
    if by_node is None:
        by_node = {id(c.node): c for c in module.calls}
    return by_node


def _value_facts(expr, scope: ScopeIR, module: ModuleIR,
                 name: str = "") -> Optional[ValueRef]:
    """A `ValueRef` for one element of a literal container.

    Deliberately narrow: a call gets the tags, class and FQNs its own call site
    resolved to, a name gets whatever that name is bound to, and anything else
    gets nothing. No new claim is made about any value.
    """
    if expr is None:
        return None
    if isinstance(expr, ast.Call):
        inner = _calls_by_node(module).get(id(expr))
        if inner is None:
            return None
        ref = ValueRef(name=name or "<elt>", scope=scope,
                       tags=sort_tags(call_output_tags(inner, scope)),
                       producer=inner, loc=inner.loc,
                       class_ir=inner.class_ir or _identity_class(inner))
        slot = slot_of(inner)
        if slot is not None:
            ref.via_fqns = slot.fqns
            ref.class_ir = ref.class_ir or slot.class_ir
        if not ref.via_fqns:
            passthrough = identity_receiver(inner)
            if passthrough is not None and passthrough.via_fqns:
                ref.via_fqns = passthrough.via_fqns
        return ref
    if isinstance(expr, ast.Subscript):
        # `g_optimizer, d_optimizer = optimizers["g"], optimizers["d"]` - the
        # BasicSR / ESRGAN / CycleGAN layout, and the shape every GAN,
        # multi-loss detector and multi-optimizer RL trainer is written in.
        return _subscript_slot(expr, scope, module)
    text = dotted_text(expr)
    if text:
        return binding_of(text, scope)
    return None


def _literal_elements(value, scope: ScopeIR, module: ModuleIR):
    """`(a(), b())` -> the per-slot ValueRefs, or `()` when it is not a literal."""
    if not isinstance(value, (ast.Tuple, ast.List)):
        return ()
    if any(isinstance(e, ast.Starred) for e in value.elts):
        return ()
    return tuple(_value_facts(e, scope, module) for e in value.elts)


def _literal_entries(value, scope: ScopeIR, module: ModuleIR):
    """`{"a": x(), "b": y()}` -> `(("a", ref), ...)` for constant string keys."""
    if not isinstance(value, ast.Dict):
        return ()
    out = []
    for key, item in zip(value.keys, value.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        ref = _value_facts(item, scope, module, name=key.value)
        if ref is not None:
            out.append((key.value, ref))
    return tuple(out)


def _adopt(ref: ValueRef, source: Optional[ValueRef]) -> ValueRef:
    """Give `ref` the type facts `source` carries, keeping its own name.

    `via_fqns` is filled from the source's own producer when the source has
    none of its own: a scheduler and a GradScaler carry no tags at all, so the
    FQNs its construction resolved to are the only thing that says what the
    value is, and losing them is what made `lr_scheduler.step()` resolve to
    nothing after `accelerator.prepare(...)`.
    """
    if source is None:
        return ref
    ref.tags = sort_tags(tuple(ref.tags) + tuple(source.tags))
    ref.producer = ref.producer or source.producer
    ref.class_ir = ref.class_ir or source.class_ir
    if not ref.via_fqns:
        ref.via_fqns = source.via_fqns or (
            _trim_via(source.producer.canonical_fqns)
            if source.producer is not None else ())
    if not ref.elements:
        ref.elements = source.elements
    if not ref.entries:
        ref.entries = source.entries
    return ref


def _subscript_slot(value, scope: ScopeIR, module: ModuleIR) -> Optional[ValueRef]:
    """`criteria["adv"]` / `optimizers[0]` read out of a **literal** container.

    VIS2-06 / VIS2-08. `criterion = criteria["adversarial"]` where `criteria` is
    a dict literal used to be an opaque subscript: the BCELoss lost its LOSS
    tag, `criterion(...)` resolved to nothing, and MLV402 (high / 0.95 on a
    BCELoss fed raw logits) went silent along with the whole MLV2xx family.
    The hop is purely syntactic and unambiguous - one literal container, one
    constant key - so it invents nothing.
    """
    if not isinstance(value, ast.Subscript):
        return None
    key = value.slice
    if isinstance(key, ast.Index):            # pragma: no cover - py<3.9 shape
        key = key.value                       # type: ignore[attr-defined]
    if not isinstance(key, ast.Constant):
        return None
    base = binding_of(dotted_text(value.value), scope) if not isinstance(
        value.value, ast.Call) else None
    if base is None:
        return None
    if isinstance(key.value, str):
        for entry_key, ref in base.entries:
            if entry_key == key.value:
                return ref
        return None
    if isinstance(key.value, bool) or not isinstance(key.value, int):
        return None
    index = key.value
    if base.elements and -len(base.elements) <= index < len(base.elements):
        return base.elements[index]
    return None


#: INFRA-R2-04 / ROB-16. `x = f(..., x, ...)` is the wrapper idiom, and the
#: names it rebinds are the names it was handed. When `f` resolves to nothing -
#: `accelerator.prepare`, `fabric.setup`, `fabric.setup_module`, a workspace
#: `def wrap(m, o): return m, o` - the old binding is the only thing anyone
#: knows about the value, and **erasing** it turns a typed value into an
#: untyped one with no diagnostic: MLV301 (high) and MLV302 both vanished on a
#: 43-line file and the verdict read "No findings: no rule fired".
def _self_wrapped(call: Optional[CallSite], name: str, scope: ScopeIR
                  ) -> Optional[ValueRef]:
    if call is None or not name:
        return None
    if K.lookup(call.fqn) is not None or slot_of(call) is not None:
        return None                  # the callee IS known; its answer wins
    short = name.split(".")[-1]
    passed = False
    for arg in list(call.args) + [call.kwarg_nodes[k] for k in sorted(call.kwarg_nodes)]:
        text = dotted_text(arg)
        if text and (text == name or text.split(".")[-1] == short):
            passed = True
            break
    if not passed:
        return None
    previous = binding_of(name, scope, exclude=call)
    if previous is None or not (previous.tags or previous.class_ir
                                or previous.via_fqns or previous.producer):
        return None
    return previous


#: DGRG2-01. `torch.load` / `torch.jit.load` carry `tags: ()`, so one
#: `model = torch.load(ckpt)` below the evaluation call replaced a MODEL-tagged
#: name with an untyped checkpoint - and, bindings being flat, that rebinding is
#: what every rule saw for the whole scope. Four findings and two nodes went
#: with it. A checkpoint restored into a name that already held a model is still
#: a model; keeping the type is strictly better than erasing it.
def _restored_into(call: Optional[CallSite], name: str, scope: ScopeIR
                   ) -> Optional[ValueRef]:
    if call is None or not name or K.role_of(call.fqn) != "LOAD":
        return None
    previous = binding_of(name, scope, exclude=call)
    if previous is not None and previous.has("MODEL"):
        return previous
    return _saved_model_behind(call)


def _saved_model_behind(load: CallSite) -> Optional[ValueRef]:
    """TAB2-02. `torch.save(model, CKPT)` ... `restored = torch.load(CKPT)`.

    "Load a checkpoint, then evaluate it" is the shape of every `eval.py` and
    `predict.py` in the world, and the restored name was untyped - so the
    evaluation helper's `model` parameter was untyped, `model(x)` resolved to
    nothing, no eval region was built, and MLV301 (**high**) and MLV302 both
    went silent with `diagnostics: []`. The Answers card did not even negate
    its guardedness clause; it dropped it, so the sentence a reader sees is
    indistinguishable from a clean report.

    The evidence is dataflow, not a name: somewhere in the same module a SAVE
    call writes a **MODEL-tagged** value to the same path expression this load
    reads. `torch.save(model.state_dict(), ...)` does not match, because the
    value written there is a STATE_DICT and carries no MODEL tag.
    """
    if not load.args:
        return None
    path = dotted_text(load.args[0]) or literal_str(load.args[0])
    if not path:
        return None
    for call in load.module.calls:
        if K.role_of(call.fqn) != "SAVE" or len(call.args) < 2:
            continue
        target = dotted_text(call.args[1]) or literal_str(call.args[1])
        if target != path:
            continue
        ref = call.receiver if call.receiver is not None else None
        saved = ref
        if saved is None:
            inner = dotted_text(call.args[0])
            saved = binding_of(inner, call.scope, at=call.loc.line) if inner else None
        if saved is not None and saved.has("MODEL"):
            return saved
    return None


#: NLP-02. The tags a projection out of a container may carry. Selecting a
#: split out of a `DatasetDict` does not change what the rows are; selecting a
#: model out of a registry dict would be an entirely different claim, so only
#: the data tags travel - the same line `helpers.DATA_TAGS` draws for the
#: `--dataflow ip` projection read.
_PROJECTION_TAGS = ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT",
                    "VAL_SPLIT", "TEST_SPLIT", "LOADER")
#: How many nested subscripts the projection is followed through.
_MAX_SUBSCRIPT_DEPTH = 3


def _trim_via(fqns) -> Tuple[str, ...]:
    return tuple(f for f in (fqns or ()) if f)[:4]


def _subscript_base(value, scope, module):
    """`(ValueRef, CallSite)` for whatever a subscript chain projects out of."""
    node, depth = value, 0
    while isinstance(node, ast.Subscript) and depth < _MAX_SUBSCRIPT_DEPTH:
        node, depth = node.value, depth + 1
    if isinstance(node, ast.Call):
        by_node = getattr(module, "_calls_by_node", None)
        if by_node is None:
            by_node = {id(c.node): c for c in module.calls}
        return None, by_node.get(id(node))
    name = dotted_text(node)
    return (binding_of(name, scope) if name else None), None


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


def _identity_class(call: Optional[CallSite]):
    """`Net().to(device)` / `model.cuda()` keeps the receiver's workspace class."""
    ref = identity_receiver(call)
    return ref.class_ir if ref is not None else None
