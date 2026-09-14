"""Evidence gathering for the three *split* rules: MLV106, MLV114, MLV121.

Temporal signals, augmenting transform pipelines, and the tf.data receiver
chain behind a `take()` / `skip()` holdout. Split out of `rules/r_holdout.py`,
which keeps the `@rule` entry points that read these.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Set, Tuple

from .. import knowledge as K
from ..ir.model import CallSite, ModuleIR
from ..ir.symbols import dotted_text
from .helpers import literal_of
from .holdout_tables import (_EVAL_NAME_RE, _TEMPORAL_COLUMN_RE, _TEMPORAL_IMPORTS,
                             _by_node, _element_calls)


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
    for call in subsets:
        target = _downstream_var(module, call)
        short = (target or "").split(".")[-1]
        if short and _EVAL_NAME_RE.match(short):
            return call, "its result is bound to %s" % target
    return None
