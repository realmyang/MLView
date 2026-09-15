"""Metric **objects** (GRAPH-R2) - HuggingFace `evaluate` and torchmetrics.

A metric object is held across a loop and read once at the end, and neither of
the two libraries that ship one had a receiver family here, so the object drew a
box and then every call *on* it resolved to nothing:

* **HuggingFace `evaluate`.** `metric = evaluate.load("accuracy")` then
  `metric.add_batch(...)` inside the loop and `metric.compute()` after it is the
  standard scoring pass of every `transformers` fine-tune written since 2022 -
  including `analyzer/tests/accuracy/corpus/hf_no_eval`. `evaluate.load` had no
  row at all, so the Evaluate lane of a whole class of repository was empty and
  `graph.diagnostics` said nothing, because the FQN *resolved*: a resolved FQN
  with no row is the silent hole `stats_tbl.py` was written about.
* **torchmetrics objects.** `knowledge._PREFIX_RULES` already landed a
  `torchmetrics.` constructor in the Evaluate lane, but with **no receiver
  family**, so `acc.update(...)` / `acc.compute()` - the entire point of holding
  one - proposed no candidate FQN at all.

Two roles are new and **no rule keys on either**. `METRIC_UPDATE` is the
in-loop accumulate (`add_batch`, `update`, `reset`): it is drawn, because a
reader's diagram has a box where the metric is fed, and it is weighted low
because it is not where the score is *decided*. `HF_METRIC` is the
`evaluate.load(...)` construction. The *read* (`compute`, `forward`,
`__call__`) takes the existing `METRIC` role deliberately: it is the same claim
`sklearn.metrics.accuracy_score` already makes, and MLV30x's eval-region
machinery already understands that role.

`torchmetrics` is a `Framework` enum member; `evaluate` ships as part of the
HuggingFace stack and is therefore `hf`, which is what the enum already spells.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry

__all__ = ["METRIC_OBJECTS", "METRIC_OBJECT_METHODS", "METRIC_FAMILY_BASE"]

HF = "hf"
TM = "torchmetrics"

METRIC_OBJECTS: Dict[str, Entry] = {}
METRIC_OBJECT_METHODS: Dict[str, Entry] = {}

# ------------------------------------------------------- HuggingFace eval ----
for _root in ("evaluate", "datasets"):
    # `datasets.load_metric` is the pre-0.4 spelling and is still the one in
    # every tutorial written before the split; it returns the same object.
    METRIC_OBJECTS["%s.load_metric" % _root] = E("metric", "eval", HF,
                                                 "HF_METRIC", (), "hf_metric")
METRIC_OBJECTS["evaluate.load"] = E("metric", "eval", HF, "HF_METRIC", (),
                                    "hf_metric")
METRIC_OBJECTS["evaluate.combine"] = E("metric", "eval", HF, "HF_METRIC", (),
                                       "hf_metric")
METRIC_OBJECTS["evaluate.evaluator"] = E("metric", "eval", HF, "HF_METRIC", (),
                                         "hf_metric")

METRIC_OBJECT_METHODS.update({
    "evaluate.EvaluationModule.compute": E("metric", "eval", HF, "METRIC"),
    "evaluate.EvaluationModule.add": E("metric", "eval", HF, "METRIC_UPDATE", (),
                                       "hf_metric", 0.4),
    "evaluate.EvaluationModule.add_batch": E("metric", "eval", HF, "METRIC_UPDATE",
                                             (), "hf_metric", 0.4),
})

# ---------------------------------------------------------- torchmetrics ----
METRIC_OBJECT_METHODS.update({
    "torchmetrics.Metric.update": E("metric", "eval", TM, "METRIC_UPDATE", (),
                                    "torchmetric", 0.4),
    "torchmetrics.Metric.compute": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.forward": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.__call__": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.reset": E("metric", "eval", TM, "METRIC_UPDATE", (),
                                   "torchmetric", 0.2),
    "torchmetrics.Metric.to": E("metric", "eval", TM, "TO_DEVICE", (),
                                "torchmetric"),
})

#: Receiver-family bases contributed to `ir/resolve_receivers._FAMILY_BASE`.
METRIC_FAMILY_BASE: Dict[str, str] = {
    "hf_metric": "evaluate.EvaluationModule",
    "torchmetric": "torchmetrics.Metric",
}
