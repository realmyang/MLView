"""What a call hands back: `ValueTag`s, identity methods and tensor roles.

Split out of `ir/bindings.py`, which re-exports everything here. Imports
`bindings_lookup`; `bindings_store` imports this module.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Sequence, Tuple

from .. import knowledge as K
from .bindings_lookup import binding_of
from .model import CallSite, ScopeIR, ValueRef, sort_tags
from .returns import slot_of
from .symbols import dotted_text

__all__ = ["call_output_tags", "identity_receiver", "IDENTITY_METHODS",
           "TENSOR_ROLES", "ESTIMATOR_ATTRS"]

#: The name shapes a *split* carries. Dataflow decides a tag; these only
#: reinforce one a producer already proposed (`_reinforce`), never mint it.

_TEST_NAME_RE = re.compile(r"(?i)^(x|y)?_?(test|holdout)")
_VAL_NAME_RE = re.compile(r"(?i)^(x|y)?_?(val|valid|validation|dev)")
_TRAIN_NAME_RE = re.compile(r"(?i)^(x|y)?_?train")
_TARGET_NAME_RE = re.compile(r"(?i)^(y|target|labels?|classes)([_0-9].*)?$")
_FEATURE_NAME_RE = re.compile(r"(?i)^(x|features?|inputs?|data)([_0-9].*)?$")

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


#: The tags a shape-preserving constructor may carry through (IP-03).
_FRAME_MAKE_TAGS = ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT",
                    "VAL_SPLIT", "TEST_SPLIT")


def _frame_make_tags(call: CallSite, scope: ScopeIR) -> Tuple[str, ...]:
    """The data tags argument 0 of `np.asarray` / `np.concatenate` carries.

    `np.concatenate([X_train, X_test])` passes a **list**, and the honest answer
    for a list is the INTERSECTION of what its members carry: stacking the
    training half onto the test half does not produce training rows, and a union
    would let MLV102 accuse a correct program of fitting on held-out data.
    """
    if not call.args:
        return ()
    first = call.args[0]
    if isinstance(first, (ast.List, ast.Tuple)):
        shared: Optional[set] = None
        for element in first.elts:
            ref = binding_of(dotted_text(element), scope)
            found = {t for t in (ref.tags if ref else ()) if t in _FRAME_MAKE_TAGS}
            shared = found if shared is None else (shared & found)
            if not shared:
                return ()
        return tuple(sorted(shared or ()))
    return tuple(t for t in _first_arg_tags(call, scope) if t in _FRAME_MAKE_TAGS)


def call_output_tags(call: CallSite, scope: ScopeIR) -> Tuple[str, ...]:
    """The `ValueTag`s of the value a call produces."""
    fqns = list(call.canonical_fqns) or ([call.fqn] if call.fqn else [])
    entry, _fqn = K.best_entry(fqns)
    role = entry["role"] if entry else None
    tags = list(entry["tags"]) if entry else []

    if call.class_ir is not None:
        # FW-RECOG: `is_model_module`, not `is_nn_module` - a LightningModule
        # instance carries MODEL exactly as an nn.Module instance does.
        if call.class_ir.is_model_module:
            tags.append("MODEL")
        elif "torch.utils.data.Dataset" in call.class_ir.resolved_bases:
            tags.append("RAW_DATA")

    if entry is None and call.target_function is not None:
        slot = slot_of(call)
        if slot is not None:
            tags.extend(slot.tags)

    receiver = call.receiver
    if role in ("FRAME_OP", "FRAME_TEMPORAL", "FRAME_RESHAPE") and receiver is not None:
        # `X = df.drop(columns=[target])` / `.copy()` / `.to_numpy()` keeps the
        # RAW_DATA / FEATURES / TARGET tags `pandas.read_csv` seeded: dropping
        # them on the first hop is what made MLV101 blind to the pandas path.
        # GRAPH-R2 adds the two families that are drawn rather than folded away
        # (`shift`, `rolling`, `groupby`, `merge`): a lag column is still the
        # same feature matrix, so the tags travel exactly as far as they did.
        tags.extend(receiver.tags)
    elif role == "FRAME_MAKE":
        # IP-03: `np.asarray(X)` / `np.concatenate([...])` / `torch.from_numpy(X)`
        # are the module-level twin of FRAME_OP - same rows, new container - so
        # the data tags travel through argument 0 rather than through a
        # receiver. Only the data tags: a MODEL or an OPTIMIZER does not go
        # through np.asarray, and carrying one would be a different claim.
        tags.extend(_frame_make_tags(call, scope))
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
