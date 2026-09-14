"""The metric tables and call utilities the held-out-integrity rules share.

Split out of `rules/r_holdout.py`, which re-exports `_CLASS_METRICS` and
`_SCORE_METRICS`: the MLV305 carve-out test asserts on those two by name.
The five `@rule` entry points stay in `r_holdout.py`, so every `RuleSpec.module`
is unchanged.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Tuple

from ..ir.model import CallSite, ModuleIR


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
