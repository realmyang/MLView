"""MLV106 / MLV114 / MLV121: what the split, the transform and the chain say.

Three rules about *where the holdout comes from* share these helpers: the
temporal signals that make a random split wrong (MLV106), the augmenting
transform pipelines and the loaders that must not see them (MLV114), and the
tf.data receiver chain a `shuffle` reaches before a `take`/`skip` pair
(MLV121).

The chain walks are deliberately bounded (eight links) and only follow names
they can bind: a dataset rebuilt inside a helper is not judged, because the
rule cannot see what it was rebuilt from.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Set, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, ModuleIR
from ..ir.symbols import dotted_text
from .helpers import literal_of
from .holdout_tables import (_EVAL_NAME_RE, _TEMPORAL_COLUMN_RE,
                             _TEMPORAL_IMPORTS, _by_node, _element_calls)


# ---------------------------------------------------------------------------
# MLV106
# ---------------------------------------------------------------------------
def _temporal_signals(ctx, module: ModuleIR) -> List[str]:
    """Independent evidence that this module's data is a time series."""
    found: List[str] = []

    def note(text: str) -> None:
        if text not in found:
            found.append(text)

    for name in module.imports or ():
        if name.split(".")[0] in _TEMPORAL_IMPORTS:
            note("the module imports %s" % name.split(".")[0])
    for call in module.calls:
        fqn = call.fqn or ""
        text = dotted_text(call.node.func) or ""
        if K.role_of(fqn) == "TEMPORAL" or fqn.endswith("to_datetime"):
            note("pandas.to_datetime at line %d" % call.loc.line)
        if "parse_dates" in call.kwarg_nodes:
            note("parse_dates= at line %d" % call.loc.line)
        if text.endswith(("date_range", "DatetimeIndex", "PeriodIndex")):
            note("%s at line %d" % (text.rsplit(".", 1)[-1], call.loc.line))
        method = call.method or ""
        if method in ("resample", "asfreq", "rolling", "shift", "diff", "tshift"):
            note("%s(...) at line %d" % (method, call.loc.line))
        if method == "sort_values" and call.args:
            literal = literal_of(ctx, call.args[0], call.scope, module)
            if literal and _TEMPORAL_COLUMN_RE.search(literal):
                note("sort_values(\"%s\") at line %d" % (literal, call.loc.line))
    return found


#: PUB-06. Cross-validators that preserve row order, so their `.split()` can
#: never be the shuffled split MLV106 is about. `KFold` / `StratifiedKFold`
#: default to `shuffle=False` and are handled by reading the constructor.
ORDERED_SPLITTERS = frozenset({
    "sklearn.model_selection.TimeSeriesSplit",
    "sklearn.model_selection.GroupKFold",
    "sklearn.model_selection.LeaveOneGroupOut",
    "sklearn.model_selection.LeavePGroupsOut",
    "sklearn.model_selection.LeaveOneOut",
    "sklearn.model_selection.LeavePOut",
    "sklearn.model_selection.PredefinedSplit",
})
#: Splitters whose order depends on their own `shuffle=` keyword (default False).
_SHUFFLE_OPTIONAL_SPLITTERS = frozenset({
    "sklearn.model_selection.KFold",
    "sklearn.model_selection.StratifiedKFold",
    "sklearn.model_selection.GroupShuffleSplit",
})


def _ordered_splitter(ctx, call: CallSite, module: ModuleIR) -> Optional[CallSite]:
    """The order-preserving cross-validator behind `<cv>.split(...)`, if any."""
    ref = call.receiver
    producer = ref.producer if ref is not None else None
    if producer is None:
        return None
    fqns = set(producer.canonical_fqns or ())
    if producer.fqn:
        fqns.add(producer.fqn)
    if fqns & ORDERED_SPLITTERS:
        return producer
    if fqns & _SHUFFLE_OPTIONAL_SPLITTERS:
        state = literal_of(ctx, producer.kwarg_nodes.get("shuffle"),
                           producer.scope, producer.module)
        if state in (None, "False"):
            return producer
    return None


# ---------------------------------------------------------------------------
# MLV114
# ---------------------------------------------------------------------------
def _augmenting_pipelines(ctx, module: ModuleIR) -> Dict[str, CallSite]:
    """`{variable: Compose call}` for every pipeline containing a random augment."""
    out: Dict[str, CallSite] = {}
    for call in module.calls:
        role = K.role_of(call.fqn)
        if role not in ("TRANSFORM_PIPE", "AUGMENT"):
            continue
        if role == "TRANSFORM_PIPE":
            if not any(K.role_of(e.fqn) == "AUGMENT" for e in _element_calls(module, call)):
                continue
        if call.var:
            out[call.var.split(".")[-1]] = call
    return out


def _workspace_dataset(ctx, producer: Optional[CallSite]) -> bool:
    """VIS2-01. Is this construction an in-workspace `Dataset` subclass?

    `augmentation_in_eval_transform` required the dataset construction to
    resolve to a knowledge row (`torchvision.datasets.ImageFolder` and friends),
    so a workspace `class MyImages(Dataset)` taking the same `transform=`
    keyword was skipped in silence - no finding and no diagnostic. Every OCR,
    detection, segmentation, re-identification and multi-task project in the
    corpus loads through its own Dataset subclass, which made "augmentation
    left on for validation" unreachable for all of them. `ctx.class_bases`
    answers this the same way MLV110's IterableDataset guard already does.
    """
    if producer is None:
        return False
    cls = producer.class_ir
    if cls is None:
        return False
    return any(base.startswith("torch.utils.data.")
               for base in (cls.resolved_bases or ()))


def _eval_loaders(ctx, module: ModuleIR) -> List[CallSite]:
    """DataLoader constructions that serve validation or test data."""
    out: List[CallSite] = []
    for call in ctx.calls_of("torch.utils.data.DataLoader"):
        if call.module is not module:
            continue
        name = (call.var or "").split(".")[-1]
        dataset = call.args[0] if call.args else call.kwarg_nodes.get("dataset")
        ref = ctx.binding_of(dotted_text(dataset), call.scope) if dataset is not None \
            else None
        if (ref is not None and ref.has("VAL_SPLIT", "TEST_SPLIT")) \
                or _EVAL_NAME_RE.match(name or ""):
            out.append(call)
    return out


def _augmenting_factories(ctx) -> Dict[str, CallSite]:
    """`{function name: Compose call}` for every one-hop transform factory.

    vision-07. `ImageFolder(root, transform=eval_transform())` and the
    Lightning `transform=self.train_transform()` idiom are how real projects
    build pipelines, and `dotted_text` on a `Call` yields the callee's name -
    which is never a Compose binding, so MLV114 saw nothing. Only a single,
    unambiguous `return Compose(...)` is followed: anything less definite is
    left unjudged, exactly as the rule leaves an unresolved name alone.
    """
    out: Dict[str, CallSite] = {}
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            if len(func.returns) != 1:
                continue
            expr = func.returns[0]
            inner = _by_node(module).get(id(expr))
            if inner is None:
                text = dotted_text(expr)
                ref = ctx.binding_of(text, func.scope) if text else None
                inner = ref.producer if ref is not None else None
            if inner is None:
                continue
            role = K.role_of(inner.fqn)
            if role == "TRANSFORM_PIPE":
                if not any(K.role_of(e.fqn) == "AUGMENT"
                           for e in _element_calls(inner.module, inner)):
                    continue
            elif role != "AUGMENT":
                continue
            out.setdefault(func.name, inner)
    return out


def _returned_pipeline(ctx, module: ModuleIR, node, factories):
    """`(Compose call, label)` for a transform built by an in-workspace call."""
    if not isinstance(node, ast.Call) or not factories:
        return None
    name = dotted_text(node.func) or dotted_text(node) or ""
    short = name.split(".")[-1]
    found = factories.get(short)
    if found is None:
        return None
    return found, "%s()" % short


# ---------------------------------------------------------------------------
# MLV121
# ---------------------------------------------------------------------------
def _upstream(module: ModuleIR, call: CallSite, depth: int = 8) -> List[CallSite]:
    """The tf.data chain behind a call: `a.shuffle(n).take(k)` -> the shuffle."""
    index = _by_node(module)
    out: List[CallSite] = []
    current: Optional[CallSite] = call
    seen: Set[int] = set()
    while current is not None and depth > 0 and id(current) not in seen:
        seen.add(id(current))
        depth -= 1
        nxt: Optional[CallSite] = None
        func = getattr(current.node, "func", None)
        inner = getattr(func, "value", None) if isinstance(func, ast.Attribute) else None
        if isinstance(inner, ast.Call):
            nxt = index.get(id(inner))
        if nxt is None and current.receiver is not None:
            nxt = current.receiver.producer
        if nxt is not None and nxt.module is module:
            out.append(nxt)
        current = nxt
    return out


#: The tf.data holdout idiom is always the **pair**: one branch takes the first
#: N rows and the other skips them. `shard` subsets a dataset for distributed
#: training, so it is never on its own evidence that a holdout was carved.
_HOLDOUT_PAIR = ("take", "skip")


def _subset_name(call: CallSite) -> str:
    return (call.fqn or "").rsplit(".", 1)[-1]


def _downstream_var(module: ModuleIR, call: CallSite, depth: int = 8) -> Optional[str]:
    """The name the value this call starts is finally bound to.

    `val_ds = shuffled.take(N).batch(B)` binds the *batch*, so the subset call's
    own `var` is empty and the only way to see the word `val` is to walk the
    chain forwards.
    """
    outer: Dict[int, CallSite] = {}
    for other in module.calls:
        func = getattr(other.node, "func", None)
        inner = getattr(func, "value", None) if isinstance(func, ast.Attribute) else None
        if isinstance(inner, ast.Call):
            outer[id(inner)] = other
    current: Optional[CallSite] = call
    seen: Set[int] = set()
    while current is not None and depth > 0 and id(current) not in seen:
        seen.add(id(current))
        depth -= 1
        if current.var:
            return current.var
        current = outer.get(id(current.node))
    return None


def _holdout_of(module: ModuleIR, subsets: List[CallSite]) -> Optional[Tuple[CallSite, str]]:
    """`(the take/skip that carves the holdout, why we believe it is one)`.

    A lone `take` is **not** a holdout: `for images, labels in train_ds.take(1)`
    is the commonest line in TensorFlow code, and the first cut of this rule
    called it a leaking train/val split at severity high, confidence 0.95, with
    a message asserting two halves that do not exist. A holdout has to be
    visible before the rule may describe one - either both sides of the idiom
    reach the same shuffle, or the subset is bound to an evaluation name.
    """
    by_method: Dict[str, CallSite] = {}
    for call in subsets:
        by_method.setdefault(_subset_name(call), call)
    if all(name in by_method for name in _HOLDOUT_PAIR):
        return by_method["take"], "both take() and skip() are taken off it"
    # PUB2-01. The second arm used to return on the NAME alone, and a name is
    # not allowed to create a claim (iron law 2). Measured on
    # optuna-examples/tensorflow/tensorflow_eager_simple.py, the effect was the
    # only high-severity false positive in 260 runs over 37 repositories:
    #
    #     (x_train, y_train), (x_valid, y_valid) = mnist.load_data()
    #     train_ds = train_ds.shuffle(60000).batch(BATCH).take(N_TRAIN)
    #     valid_ds = valid_ds.shuffle(10000).batch(BATCH).take(N_VALID)
    #
    # Two already-disjoint arrays, one `take()` on each to cap how many batches
    # a trial consumes, and **no `skip()` anywhere in the file**. MLView
    # reported high / 0.95 / `certain` on the second line only - because the
    # variable is called `valid_ds` - and asserted that the take "carves out
    # the holdout" and that "every validation row has been trained on by epoch
    # two". Three statements, all false about that file; the identical chain on
    # the line above, with a different variable name, was silent.
    #
    # A `take()` with no complementary `skip()` on the same shuffled receiver
    # is a subsample, not a holdout. The name may still SELECT which half of a
    # real pair is described - `_HOLDOUT_PAIR` above is that pair - but it may
    # not assert one into existence. All three round-1 true positives (keras-io
    # pointnet.py, siamese_network.py, xray_classification_with_tpus.py) carry
    # an explicit `take` and `skip` on the same shuffled receiver, so the pair
    # rule keeps 100% of the known true positives.
    return None
