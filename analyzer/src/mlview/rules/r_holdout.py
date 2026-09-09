"""Held-out-integrity rules (ANA-9): is the number you are reading honest?

MLV106 a random split over apparently temporal data - MLV114 random augmentation
in the evaluation transform - MLV121 a tf.data `shuffle` feeding a `take` /
`skip` holdout - MLV305 a class metric computed on raw logits or probabilities -
MLV306 a ranking metric fed hard labels.

This is the class no general-purpose linter touches: none of these is a syntax
error, every one of them produces a number that looks fine and is wrong.
MLV121 is the extreme case - `shuffle(1024)` before `take()` / `skip()`
reshuffles on every epoch, so the training and validation halves swap rows every
pass and the holdout stops existing.

**What these rules cannot analyze.**

* **MLV305** needs the prediction value to carry `LOGITS` or `PROBS`. A
  prediction produced by a helper function looks unproduced to a
  flow-insensitive IR, so the finding is **de-rated** (evidence weight 0.6)
  rather than dropped, and the score-metric carve-out
  (`roc_auc_score`, `average_precision_score`, `log_loss` and the rest of
  `_SCORE_METRICS`) is exhaustive and checked twice: those metrics legitimately
  take scores and this rule never fires on one.
* **MLV106** requires **two independent** temporal signals in the same module.
  The catalog sketch allowed a single signal at x0.6; ANA-12 forbids spending
  precision on a guess, so one signal is silence here.
* **MLV114** requires the augmenting `Compose` to reach an evaluation loader
  **directly** - transform to dataset to loader. An augmented dataset that is
  later `random_split` into a training and a validation half is not judged: the
  analyzer cannot tell which half inherits what, and saying so is better than
  guessing (this is exactly the shape `samples/vision_pipeline` writes).
* **MLV121** follows the tf.data receiver chain through at most eight links,
  and only through names it can bind. A dataset rebuilt inside a helper is not
  judged, and a **holdout must be visible before the rule describes one**: the
  same shuffled receiver has to reach both a `take` and a `skip`, or the subset
  has to be bound to an evaluation name. A lone `take` is a peek - `for images,
  labels in train_ds.take(1)` is the commonest line in TensorFlow code - and
  calling it a leaking train/val split was a statement about code that does not
  exist. A holdout whose two halves come off *different* `shuffle` calls is
  judged only by the name test.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ModuleIR
from ..ir.symbols import dotted_text
from .helpers import literal_of, value_sources
from .registry import rule

__all__ = ["random_split_on_temporal_data", "augmentation_in_eval_transform",
           "tfdata_shuffle_before_holdout", "metric_on_raw_scores",
           "ranking_metric_on_hard_labels"]

# ------------------------------------------------------------------ metrics
#: Metrics that take **class predictions**. Exhaustive on purpose: a metric that
#: is not on this list is never judged by MLV305.
_CLASS_METRICS = frozenset({
    "sklearn.metrics.accuracy_score", "sklearn.metrics.balanced_accuracy_score",
    "sklearn.metrics.f1_score", "sklearn.metrics.precision_score",
    "sklearn.metrics.recall_score", "sklearn.metrics.confusion_matrix",
    "sklearn.metrics.classification_report", "sklearn.metrics.cohen_kappa_score",
    "sklearn.metrics.matthews_corrcoef", "sklearn.metrics.jaccard_score",
    "sklearn.metrics.precision_recall_fscore_support",
    "sklearn.metrics.hamming_loss", "sklearn.metrics.zero_one_loss",
    "torchmetrics.functional.accuracy", "torchmetrics.functional.f1_score",
    "torchmetrics.functional.precision", "torchmetrics.functional.recall",
})

#: The score-metric carve-out (ROADMAP ANA-9: "must be exhaustive"). These take
#: continuous scores by design and MLV305 never fires on one.
_SCORE_METRICS = frozenset({
    "sklearn.metrics.roc_auc_score", "sklearn.metrics.average_precision_score",
    "sklearn.metrics.log_loss", "sklearn.metrics.roc_curve",
    "sklearn.metrics.precision_recall_curve", "sklearn.metrics.brier_score_loss",
    "sklearn.metrics.top_k_accuracy_score", "sklearn.metrics.ndcg_score",
    "sklearn.metrics.dcg_score",
    "sklearn.metrics.label_ranking_average_precision_score",
    "torchmetrics.functional.auroc",
})

#: The two ranking metrics MLV306 judges.
_RANKING_METRICS = frozenset({"sklearn.metrics.roc_auc_score",
                              "sklearn.metrics.average_precision_score"})

#: Names whose appearance in the producing expression means the value has
#: already been turned into class predictions.
_DECIDED = ("argmax", "round", "topk", "astype", "argsort", "where", "sign",
            "greater", "threshold", "rint", "argpartition")

_EVAL_NAME_RE = re.compile(r"(?i)^(val|valid|validation|test|eval|holdout)_?"
                           r"(loader|dl|ds|dataset|data|set|batches)?$")
_TEMPORAL_COLUMN_RE = re.compile(r"(?i)(date|time|timestamp|datetime|period|month|"
                                 r"week|day|year|hour)")
_TEMPORAL_IMPORTS = ("statsmodels", "prophet", "fbprophet", "darts", "pmdarima",
                     "sktime", "tsfresh")


def _short(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _anchor(ctx, call: CallSite):
    return ctx.node_for_call(call) or ctx.unit_for_call(call)


def _static(scope) -> List[Tuple[str, str, float]]:
    if scope is None or scope.is_dynamic:
        return []
    return [("scope_static", "no dynamic constructs in %s" % scope.qualname, 1.0)]


def _by_node(module: ModuleIR) -> Dict[int, CallSite]:
    return {id(call.node): call for call in module.calls}


def _element_calls(module: ModuleIR, call: CallSite) -> List[CallSite]:
    """Every recorded call written inside this call's argument list."""
    index = _by_node(module)
    out: List[CallSite] = []
    for node in list(call.args) + list(call.kwarg_nodes.values()):
        for child in ast.walk(node):
            found = index.get(id(child))
            if found is not None and found is not call:
                out.append(found)
    return out


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


@rule(code="MLV106", severity="medium", base_prior=0.70, frameworks=["sklearn", "pandas"],
      rule_version=1, tags=["leakage", "data"],
      title="Random split used on apparently temporal data",
      why="A shuffled split puts tomorrow's rows in the training half and yesterday's "
          "in the test half, so the model is scored on interpolating a series it has "
          "already seen the future of and the reported error is optimistic.",
      fix_hint="Use TimeSeriesSplit(n_splits=...) or a chronological cut "
               "(train = df[df.date < cutoff]) instead of a shuffled split.")
def random_split_on_temporal_data(ctx) -> Iterable[Issue]:
    """Phrased as a question, and it takes **two** independent signals to ask
    it: one is a coincidence in any dataset that happens to carry a date."""
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        signals = _temporal_signals(ctx, module)
        if len(signals) < 2:
            continue
        for call in module.calls:
            if K.role_of(call.fqn) != "SPLIT":
                continue
            shuffle = literal_of(ctx, call.kwarg_nodes.get("shuffle"), call.scope, module)
            if shuffle == "False":
                continue
            node = _anchor(ctx, call)
            weight = 1.0 if len(signals) > 2 else 0.8
            evidence = [
                ("fqn_resolved", "%s resolved to %s"
                 % (call.short_name, call.fqn or "a split"), 1.0),
                ("context_confirmed",
                 "%d independent temporal signals in %s: %s"
                 % (len(signals), relpath, "; ".join(signals[:3])), weight),
                ("negation_absent",
                 "the split does not pass shuffle=False", 1.0),
            ] + _static(call.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d shuffles rows that look like a time series (%s). "
                        "Is a random split what you meant here?"
                        % (_short(call), call.loc.file, call.loc.line,
                           "; ".join(signals[:2])),
                loc=call.loc, node_ids=[node] if node is not None else (),
                related=[("split_site", call.loc, "the shuffled split happens here")],
                evidence=evidence, stage="data", dynamic=call.scope.is_dynamic))
    return issues


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


@rule(code="MLV114", severity="medium", base_prior=0.90,
      frameworks=["torchvision", "torch"],
      rule_version=1, tags=["evaluation", "data"],
      title="Random augmentation in the evaluation transform pipeline",
      why="Every evaluation pass sees differently cropped and flipped images, so the "
          "validation curve moves for reasons that have nothing to do with the model "
          "and the score is systematically worse than the model deserves.",
      fix_hint="Give the evaluation dataset its own Compose with only the "
               "deterministic steps (Resize / CenterCrop / ToTensor / Normalize).")
def augmentation_in_eval_transform(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        pipelines = _augmenting_pipelines(ctx, module)
        if not pipelines:
            continue
        loaders = _eval_loaders(ctx, module)
        if not loaders:
            continue
        for loader in loaders:
            dataset_node = loader.args[0] if loader.args \
                else loader.kwarg_nodes.get("dataset")
            name = dotted_text(dataset_node) if dataset_node is not None else None
            ref = ctx.binding_of(name, loader.scope) if name else None
            producer = ref.producer if ref is not None else None
            if producer is None or K.role_of(producer.fqn) != "DATASET":
                continue
            hit = None
            for key in ("transform", "transforms", "target_transform"):
                node = producer.kwarg_nodes.get(key)
                text = dotted_text(node) if node is not None else None
                if text and text.split(".")[-1] in pipelines:
                    hit = (key, pipelines[text.split(".")[-1]], text)
                    break
            if hit is None:
                continue
            key, compose, text = hit
            augments = [e for e in _element_calls(module, compose)
                        if K.role_of(e.fqn) == "AUGMENT"]
            anchor = _anchor(ctx, compose)
            evidence = [
                ("fqn_resolved", "%s resolved to %s"
                 % (text, compose.fqn or "a transform pipeline"), 1.0),
                ("dataflow_direct",
                 "%s -> %s(%s=) at line %d -> %s at line %d"
                 % (text, producer.short_name, key, producer.loc.line,
                    loader.var or "an evaluation loader", loader.loc.line), 1.0),
                ("knowledge_table",
                 "the pipeline contains %s, whose role is AUGMENT"
                 % ", ".join(sorted({a.short_name for a in augments})), 1.0),
            ] + _static(compose.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d applies random augmentation (%s) and reaches the "
                        "evaluation loader %s at line %d through %s."
                        % (text, compose.loc.file, compose.loc.line,
                           ", ".join(sorted({a.short_name for a in augments})),
                           loader.var or "a DataLoader", loader.loc.line,
                           producer.short_name),
                loc=compose.loc, node_ids=[anchor] if anchor is not None else (),
                related=[("construction", producer.loc,
                          "the evaluation dataset is built here"),
                         ("eval_loop", loader.loc, "and served by this loader")],
                evidence=evidence, stage="preprocess",
                dynamic=compose.scope.is_dynamic))
    return issues


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


@rule(code="MLV121", severity="high", base_prior=0.95, frameworks=["tf", "keras"],
      rule_version=1, tags=["leakage", "data"],
      title="tf.data shuffle feeds a take/skip holdout",
      why="tf.data reshuffles the buffer on every epoch by default, so take() and "
          "skip() carve out a different training and validation half each pass: every "
          "validation row has been trained on by epoch two and the holdout has stopped "
          "existing.",
      fix_hint="Pass reshuffle_each_iteration=False to shuffle(), or split with "
               "take()/skip() first and shuffle only the training half afterwards.")
def tfdata_shuffle_before_holdout(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    reached: Dict[int, List[CallSite]] = {}
    order: List[CallSite] = []
    for holdout in ctx.calls_with_role("TFDATA_SUBSET"):
        for shuffle in _upstream(holdout.module, holdout):
            if K.role_of(shuffle.fqn) != "TFDATA_SHUFFLE":
                continue
            if id(shuffle) not in reached:
                reached[id(shuffle)] = []
                order.append(shuffle)
            reached[id(shuffle)].append(holdout)
            break
    for shuffle in order:
        literal = literal_of(ctx, shuffle.kwarg_nodes.get("reshuffle_each_iteration"),
                             shuffle.scope, shuffle.module)
        if literal == "False":
            continue
        found = _holdout_of(shuffle.module, reached[id(shuffle)])
        if found is None:
            continue
        holdout, why = found
        node = _anchor(ctx, shuffle)
        evidence = [
            ("fqn_resolved", "%s resolved to %s"
             % (_short(shuffle), shuffle.fqn or "Dataset.shuffle"), 1.0),
            ("dataflow_direct",
             "the shuffled dataset reaches %s at line %d through the tf.data "
             "receiver chain, and %s" % (_short(holdout), holdout.loc.line, why), 1.0),
            ("negation_absent",
             "shuffle() does not pass reshuffle_each_iteration=False", 1.0),
        ] + _static(shuffle.scope)
        related = [("split_site", holdout.loc, "the holdout is carved out here"),
                   ("call_site", shuffle.loc, "the shuffle happens here")]
        for other in reached[id(shuffle)]:
            if other is not holdout and _subset_name(other) in _HOLDOUT_PAIR:
                related.append(("split_site", other.loc,
                                "and the other half is taken here"))
                break
        issues.append(ctx.issue(
            message="%s at %s:%d shuffles before %s at line %d carves out the "
                    "holdout, and reshuffle_each_iteration defaults to True, so the "
                    "two halves are re-drawn every epoch."
                    % (_short(shuffle), shuffle.loc.file, shuffle.loc.line,
                       _short(holdout), holdout.loc.line),
            loc=shuffle.loc, node_ids=[node] if node is not None else (),
            related=related,
            evidence=evidence, stage="data", dynamic=shuffle.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV305 / MLV306 - the prediction argument
# ---------------------------------------------------------------------------
def _prediction_arg(call: CallSite) -> Optional[ast.expr]:
    """sklearn's convention is `(y_true, y_pred)`; the kwarg spelling counts too."""
    for key in ("y_pred", "y_score", "preds", "output"):
        node = call.kwarg_nodes.get(key)
        if node is not None:
            return node
    if len(call.args) >= 2:
        return call.args[1]
    return None


def _decided(ctx, node: ast.expr, call: CallSite) -> bool:
    """Has this expression already been turned into class predictions?"""
    for child in ast.walk(node):
        if isinstance(child, (ast.Compare, ast.Subscript)):
            return True
        text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute,
                                                        ast.Call)) else None
        if text and text.rsplit(".", 1)[-1] in _DECIDED:
            return True
    name = dotted_text(node)
    if not name:
        return False
    for source in value_sources(ctx, name, call.scope):
        if source.rsplit(".", 1)[-1] in _DECIDED:
            return True
        ref = ctx.binding_of(source, call.scope)
        producer = ref.producer if ref is not None else None
        if producer is None:
            continue
        if K.role_of(producer.fqn) == "ARGMAX":
            return True
        for arg in producer.args:
            for child in ast.walk(arg):
                text = dotted_text(child) if isinstance(child, ast.Call) else None
                if text and text.rsplit(".", 1)[-1] in _DECIDED:
                    return True
        if (producer.method or producer.short_name) in _DECIDED:
            return True
    return False


def _scored_value(ctx, call: CallSite, node: ast.expr):
    """`(tags, producer, name)` for the prediction argument of a metric call."""
    index = _by_node(call.module)
    if isinstance(node, ast.Call):
        producer = index.get(id(node))
        if producer is None:
            return (), None, dotted_text(node)
        return K.tags_of(producer.fqn), producer, dotted_text(node)
    name = dotted_text(node)
    ref = ctx.binding_of(name, call.scope) if name else None
    if ref is None:
        return (), None, name
    return tuple(ref.tags), ref.producer, name


# ---------------------------------------------------------------------------
# MLV305
# ---------------------------------------------------------------------------
@rule(code="MLV305", severity="medium", base_prior=0.85,
      frameworks=["sklearn", "torch"],
      rule_version=1, tags=["evaluation", "correctness"],
      title="Class metric computed on raw scores instead of predicted classes",
      why="accuracy_score compares floats to integer labels, so the reported accuracy "
          "is roughly the chance rate no matter how good the model is - and it is a "
          "number, not an error, so nobody notices.",
      fix_hint="Take the class first: preds = logits.argmax(axis=1) (or a 0.5 "
               "threshold for a binary head), then pass preds to the metric.")
def metric_on_raw_scores(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for call in module.calls:
            fqn = call.fqn or ""
            if fqn in _SCORE_METRICS or fqn not in _CLASS_METRICS:
                continue                # the carve-out, checked before anything else
            node = _prediction_arg(call)
            if node is None:
                continue
            tags, producer, name = _scored_value(ctx, call, node)
            decided = _decided(ctx, node, call)
            if not ({"LOGITS", "PROBS"} & set(tags)):
                # A value that is visibly argmaxed / rounded / thresholded is
                # *checked*, not untraced: noting it would make every correct
                # program carry a coverage diagnostic (11.18 acceptance).
                if name and not tags and not decided:
                    ctx.untraced(call, name,
                                 "the prediction argument carries no LOGITS / PROBS "
                                 "tag, so MLV305 could not tell scores from classes")
                continue
            if decided:
                continue
            anchor = _anchor(ctx, call)
            weight = 1.0 if producer is not None else 0.6
            detail = ("%s is produced by %s" % (name, producer.fqn or producer.short_name)
                      if producer is not None
                      else "%s carries %s but its producer is outside this scope, so "
                           "the finding is de-rated" % (name, "/".join(sorted(tags))))
            evidence = [
                ("fqn_resolved", "%s resolved to %s" % (call.short_name, fqn), 1.0),
                ("dataflow_direct", detail, weight),
                ("negation_absent",
                 "no argmax / round / threshold / topk between the model output and "
                 "the metric", 1.0),
                ("knowledge_table",
                 "%s takes class predictions; the score metrics (%s) are carved out "
                 "and never judged" % (call.short_name, "roc_auc_score, "
                                       "average_precision_score, log_loss"), 1.0),
            ] + _static(call.scope)
            related = [("call_site", call.loc, "the metric is computed here")]
            if producer is not None:
                related.append(("construction", producer.loc,
                                "%s is produced here" % name))
            issues.append(ctx.issue(
                message="%s at %s:%d scores %s, which carries %s rather than class "
                        "predictions, so it compares continuous values with integer "
                        "labels."
                        % (call.short_name, call.loc.file, call.loc.line, name,
                           "/".join(sorted({t for t in tags if t in ("LOGITS", "PROBS")}))),
                loc=call.loc, node_ids=[anchor] if anchor is not None else (),
                related=related, evidence=evidence, stage="eval",
                dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV306
# ---------------------------------------------------------------------------
@rule(code="MLV306", severity="low", base_prior=0.90, frameworks=["sklearn"],
      rule_version=1, tags=["evaluation", "correctness"],
      title="Ranking metric fed hard labels",
      why="ROC AUC over 0/1 predictions collapses to a two-point curve, so the number "
          "you report is balanced accuracy wearing an AUC label and it hides exactly "
          "the threshold behaviour AUC exists to show.",
      fix_hint="Pass scores: roc_auc_score(y_true, clf.predict_proba(X)[:, 1]) or "
               "clf.decision_function(X).")
def ranking_metric_on_hard_labels(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for call in module.calls:
            if (call.fqn or "") not in _RANKING_METRICS:
                continue
            node = _prediction_arg(call)
            if node is None:
                continue
            tags, producer, name = _scored_value(ctx, call, node)
            if producer is None or K.role_of(producer.fqn) != "PREDICT":
                continue
            if "PREDS" not in tags:
                continue
            anchor = _anchor(ctx, call)
            evidence = [
                ("fqn_resolved", "%s resolved to %s" % (call.short_name, call.fqn), 1.0),
                ("dataflow_direct",
                 "%s comes from %s, whose knowledge-table tag is PREDS"
                 % (name, producer.fqn or "predict()"), 1.0),
                ("knowledge_table",
                 "predict_proba carries PROBS and decision_function carries LOGITS; "
                 "neither was used here", 1.0),
            ] + _static(call.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d ranks %s, which comes from predict() and holds "
                        "hard class labels rather than scores."
                        % (call.short_name, call.loc.file, call.loc.line, name),
                loc=call.loc, node_ids=[anchor] if anchor is not None else (),
                related=[("call_site", call.loc, "the ranking metric is computed here"),
                         ("construction", producer.loc,
                          "%s is produced by predict() here" % name)],
                evidence=evidence, stage="eval", dynamic=call.scope.is_dynamic))
    return issues
