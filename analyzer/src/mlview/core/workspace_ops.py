"""Op nodes for calls whose meaning comes from the **workspace**, not a table.

`core/build_ops.py` mints an op for every call a knowledge row recognises. Three
shapes of call carry just as much meaning and used to mint nothing at all,
because the thing they name is defined in the analyzed project rather than in a
framework:

1. **construction** - ``model = SmallCNN()``. The call resolved to a workspace
   class, so it was mapped onto that class's own unit node and the construction
   site vanished. A reader's diagram has a box where the model is *built*, not
   only where it is *declared*, and every edge that should start at the instance
   started at the definition instead.
2. **invocation** - ``logits = model(images)`` / ``loss = criterion(out, y)``.
   Role ``FORWARD`` is transparent by design (``self.conv(x)`` inside a
   ``forward`` belongs to the layer it calls, not to a box of its own), and that
   correct rule swallowed the *outer* forward pass too: the single most drawn
   arrow in any training diagram had no node to land on.
3. **factory return** - ``model = build_from_cfg(...)``, ``opt =
   build_optimizer(model, cfg)``. `ir.returns` already knows what such a
   function hands back; nothing drew it. When the return cannot be typed at all
   the honest answer is ANA-5a's: an `unknown` box that names the construct that
   defeated the analyzer, rather than a silently smaller graph.

Every node minted here is deliberately **vote-free**: it never contributes to
`GraphBuilder._op_votes`, so no unit can change lane because of this module, and
the ones whose lane is a property of *where they run* rather than of what they
are (a forward pass is training in a train loop and evaluation in an eval loop)
are registered in `GraphBuilder.inherit_stage` and re-staged from their parent
once `_assign_stages` has decided the parent's lane.

Iron law 1 holds throughout: nothing here invents an FQN. A node's `fqn` is set
only when a *knowledge row* named it, which is why the factory nodes carry their
returned symbol in the sublabel instead.
"""

from __future__ import annotations

import ast
from typing import Dict, Optional, Set, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, ClassIR, ModuleIR
from ..ir.returns import slot_of
from .graph import Evidence, Node

__all__ = ["construction_op", "invoke_op", "factory_op", "class_shape",
           "is_loss_class", "restage_inherited"]

#: Tags a factory return may be drawn from when it names no symbol at all. Only
#: the four that describe an *object*: a FEATURES or TRAIN_SPLIT return is data
#: travelling through a helper, and drawing a box for it would double every
#: preprocessing step.
_TAG_SHAPE: Dict[str, Tuple[str, str]] = {
    "MODEL": ("model", "model"),
    "LOADER": ("dataloader", "data"),
    "OPTIMIZER": ("optimizer", "train"),
    "LOSS": ("loss", "objective"),
}

#: Roles whose value is an **object with an identity** - something a reader
#: keeps in mind and points at later. A factory that returns one gets a box at
#: its call site; a factory that returns a *number* or a *matrix* does not,
#: because the box would stand for a value the callee already drew and the
#: diagram would say the same thing twice. `accuracy = score(preds, y)` and
#: `X = load(path)` are the two that measured this: on the 525-file synthetic
#: they were 150 of 437 new cards and not one of them named an object.
_FACTORY_ROLES = frozenset({
    "MODEL_CLS", "MODEL_FACTORY", "ESTIMATOR", "PIPELINE", "CV_SEARCH",
    "CONTAINER", "LAYER", "LOSS_CLS", "OPTIMIZER", "SCHEDULER", "GRAD_SCALER",
    "LOADER", "DATASET", "DATASET_HF", "SAMPLER", "GENERATOR", "COLLATOR",
    "TRANSFORMER", "STATELESS_TRANSFORMER", "TRANSFORM_PIPE", "AUGMENT",
    "SPLITTER", "HF_MODEL", "HF_TOKENIZER", "HF_TRAINER", "HF_PIPELINE",
    "KERAS_MODEL", "LIGHTNING_MODULE", "LIGHTNING_TRAINER", "LIGHTNING_DM",
    "ACCELERATOR", "FABRIC", "WRAP_MODEL", "GBM_TRAIN", "TIMM_MODEL",
})

#: sklearn bases that make a workspace class a transformer rather than a model.
_SKLEARN_TRANSFORMER = ("sklearn.base.TransformerMixin",
                        "sklearn.preprocessing", "sklearn.decomposition",
                        "sklearn.impute", "sklearn.feature_selection",
                        "sklearn.feature_extraction")


def is_loss_class(cls: Optional[ClassIR]) -> bool:
    """Does this workspace class compute a loss?

    Structural, never nominal: the question asked is whether the class's
    ``forward`` **returns a value tagged LOSS** - which is true exactly when its
    body reaches a ``LOSS_FN`` / ``LOSS_CLS`` symbol the knowledge tables already
    name. A class called ``FocalLoss`` that returns logits is a model here, and a
    class called ``Objective`` that returns ``F.cross_entropy(...)`` is a loss,
    which is the right way round.
    """
    if cls is None:
        return False
    forward = (cls.methods or {}).get("forward")
    summary = getattr(forward, "return_summary", None) if forward is not None else None
    scalar = getattr(summary, "scalar", None) if summary is not None else None
    return bool(scalar is not None and "LOSS" in (scalar.tags or ()))


def class_shape(cls: ClassIR, enclosing: Optional[ClassIR]
                ) -> Tuple[Optional[str], Optional[str], str]:
    """`(kind, stage, why)` for constructing a workspace class, or `(None, ...)`.

    `None` means *this class says nothing the diagram can use* - a plain helper
    class - and the caller keeps the pre-existing behaviour of folding the call
    onto the class's unit node.
    """
    if cls.is_model_module:
        if is_loss_class(cls):
            return "loss", "objective", "%s.forward returns a loss" % cls.name
        if enclosing is not None and enclosing.is_model_module:
            # A model built inside another model's body is a submodule, and the
            # reader's diagram draws it exactly where `nn.Conv2d` is drawn.
            return "layer", "model", ("%s is built inside %s, so it is a submodule"
                                      % (cls.name, enclosing.name))
        return "model", "model", "%s subclasses a model base" % cls.name
    bases = cls.resolved_bases or ()
    if any(b.startswith("torch.utils.data.") for b in bases):
        return "dataset", "data", "%s subclasses a torch Dataset" % cls.name
    if any(b.endswith("LightningDataModule") for b in bases):
        return "dataset", "data", "%s is a LightningDataModule" % cls.name
    if any(b.startswith("sklearn.") for b in bases):
        if any(b.startswith(_SKLEARN_TRANSFORMER) for b in bases):
            return "transform", "preprocess", "%s is an sklearn transformer" % cls.name
        return "model", "model", "%s subclasses an sklearn estimator" % cls.name
    return None, None, ""


# ---------------------------------------------------------------------------
# minting
# ---------------------------------------------------------------------------

def _mint(builder, module: ModuleIR, call: CallSite, kind: str, stage: str,
          sublabel: Optional[str], evidence, confidence: float,
          inherit: bool = False, framework: Optional[str] = None) -> Node:
    parent = builder._owning_unit(call)
    qualname = "%s.%s" % (call.scope.qualname, call.var or call.short_name)
    node = builder._make_node(
        module.relpath, qualname, kind,
        level="op", stage=stage, label=call.var or "%s()" % call.short_name,
        sublabel=sublabel, framework=framework, var=call.var,
        loc=call.loc, parent=parent.id if parent else None,
        attrs=dict(call.kwargs), dynamic=call.scope.is_dynamic,
        confidence=confidence, stageEvidence=list(evidence))
    builder.node_for_call[id(call)] = node
    builder.call_for_node[node.id] = call
    if parent is not None:
        builder._children.setdefault(parent.id, []).append(node)
    if inherit:
        builder.inherit_stage.add(node.id)
    builder._attach_ports(node, call)
    return node


def construction_op(builder, call: CallSite, module: ModuleIR) -> Optional[Node]:
    """`model = SmallCNN()` - the construction site, not the class definition."""
    cls = call.class_ir
    if cls is None or call.receiver is not None or call.method:
        return None
    kind, stage, why = class_shape(cls, call.enclosing_class)
    if kind is None or stage is None:
        return None
    sublabel = " · ".join(
        [cls.name] + ["%s=%s" % (k, _clip(call.kwargs[k])) for k in sorted(call.kwargs)[:2]]
    )
    confidence = 0.9 if not call.scope.is_dynamic else 0.63
    return _mint(builder, module, call, kind, stage, sublabel,
                 [Evidence("class_base", why, 1.0)], confidence)


def invoke_op(builder, call: CallSite, module: ModuleIR, entry) -> Optional[Node]:
    """`logits = model(images)` / `loss = criterion(out, y)`.

    Only the **outer** forward pass: a call written inside a model class's own
    body is the layer chain `TRANSPARENT_ROLES` exists to keep quiet, and stays
    quiet. The receiver has to be an object the analyzer already believes is a
    model or a criterion - a tag or a resolved class, never a name.
    """
    if not entry or entry.get("role") != "FORWARD":
        return None
    if call.method != "__call__" or call.receiver is None:
        return None
    enclosing = call.enclosing_class
    if enclosing is not None and enclosing.is_model_module:
        return None
    ref = call.receiver
    name = call.receiver_name or ref.name
    if ref.has("LOSS") or is_loss_class(ref.class_ir):
        kind, why = "loss", "%s is a criterion, so calling it computes the loss" % name
    elif (ref.has("MODEL") or (ref.class_ir is not None and ref.class_ir.is_model_module)
          or _model_family(ref)):
        kind, why = "predict", "%s is a model, so calling it is a forward pass" % name
    else:
        return None
    confidence = 0.85 if not call.scope.is_dynamic else 0.6
    return _mint(builder, module, call, kind, "model", "%s(...)" % name,
                 [Evidence("dataflow_direct", why, 1.0),
                  Evidence("context_confirmed",
                           "drawn in the lane of the unit it runs in", 0.9)],
                 confidence, inherit=True)


def factory_op(builder, call: CallSite, module: ModuleIR) -> Optional[Node]:
    """`opt = build_optimizer(model, cfg)` - the object a workspace factory returns.

    `ir.returns` already merges the callee's `return` expressions; this draws
    what it found. A return the pass could not type at all still gets a box,
    carrying the construct that defeated it, because a factory nobody can follow
    is a fact about the program and not a licence to draw a smaller graph.
    """
    func = call.target_function
    if func is None or call.receiver is not None or call.method:
        # A *method* reached through a receiver - `model(images)` resolves to
        # `SmallCNN.forward`, `self.head(x)` to a layer - is not a factory call.
        # Drawing its return type here would put a `layer` box on the forward
        # pass and steal the `predict` node `invoke_op` mints for it.
        return None
    if not _value_is_used(call, module):
        return None
    slot = slot_of(call)
    if slot is None:
        return None
    kind = stage = None
    detail = ""
    entry, fqn = K.best_entry(slot.fqns)
    if entry is not None and entry.get("role") in _FACTORY_ROLES:
        kind, stage = entry["kind"], entry.get("stage") or "config"
        detail = "%s() returns %s" % (func.name, fqn)
    elif slot.class_ir is not None:
        kind, stage, detail = class_shape(slot.class_ir, call.enclosing_class)
    if kind is None:
        for tag in ("MODEL", "LOADER", "OPTIMIZER", "LOSS"):
            if tag in (slot.tags or ()):
                kind, stage = _TAG_SHAPE[tag]
                detail = "%s() returns a value tagged %s" % (func.name, tag)
                break
    if kind is not None and stage is not None:
        return _mint(builder, module, call, kind, stage,
                     "%s()" % func.name,
                     [Evidence("cross_file", detail, 0.9)], 0.75)
    if slot.opaque:
        return _mint(builder, module, call, "unknown", "config",
                     "unresolved factory · %s" % slot.opaque,
                     [Evidence("scope_static",
                               "%s() returns %s, so its value could not be typed"
                               % (func.name, slot.opaque), 0.5)],
                     0.35, inherit=True)
    return None


def restage_inherited(builder) -> None:
    """Give every `inherit_stage` op the lane its parent unit ended up in."""
    for node_id in sorted(builder.inherit_stage):
        node = builder._by_id.get(node_id)
        if node is None:            # pragma: no cover - defensive
            continue
        parent = builder._by_id.get(node.parent or "")
        if parent is not None and parent.stage:
            node.stage = parent.stage


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clip(text: str, width: int = 20) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


#: Receiver families whose object is a model even though no workspace class
#: backs it - `AutoModel.from_pretrained(...)`, a Keras `Model`, a
#: `LightningModule` reached through a parameter.
_MODEL_FAMILIES = ("module", "keras_model", "lightning_module")


def _model_family(ref) -> bool:
    from ..ir.resolve_receivers import _family_of_ref
    return _family_of_ref(ref) in _MODEL_FAMILIES


def _not_used_here(module: ModuleIR) -> Set[int]:
    """`id()` of every call whose value this scope does not keep.

    Two shapes, and the complement of them is what this module means by *used*:

    * a **bare expression statement** - `log_everything()` on a line of its own
      throws the value away, and a card for the object it built would be a card
      for something nobody holds;
    * a **`return` / `yield`** - the value leaves for the caller, and the caller
      is where it gets a name and a box. Without this, `return build(group,
      name)` drew a factory card inside `build_from_cfg` *and* a second one at
      `model = build_from_cfg(...)`, which is the same object twice.

    Stated as the complement because the ways a value can be used are
    open-ended: `build_from_cfg(...).to(device)` binds nothing of its own, and
    `optimizers = (build_opt(), build_opt())` binds neither element.
    """
    cached = getattr(module, "_not_used_here", None)
    if cached is not None:
        return cached
    passed: Set[int] = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            passed.add(id(node.value))
        elif isinstance(node, (ast.Return, ast.Yield)) and isinstance(node.value, ast.Call):
            passed.add(id(node.value))
    setattr(module, "_not_used_here", passed)
    return passed


def _value_is_used(call: CallSite, module: ModuleIR) -> bool:
    return bool(call.var) or id(call.node) not in _not_used_here(module)
