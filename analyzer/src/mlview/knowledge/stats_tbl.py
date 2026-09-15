"""Time-series estimators and metric objects (GRAPH-R2).

Three families the knowledge tables had never heard of, each of which makes a
whole class of project unreadable when it is missing:

* **statsmodels / Prophet.** A forecasting script has no `nn.Module`, no
  sklearn estimator and no `fit`/`predict` the tables recognise, so
  `SARIMAX(...).fit()` and `model.forecast(24)` drew nothing and the Model,
  Train and Evaluate lanes of a whole repository were empty. `fit()` returns a
  *results* object, so the row for `fit` keeps the receiver family - that is
  what lets `res.forecast(...)` resolve one line later.
* **HuggingFace `evaluate`.** `metric = evaluate.load("accuracy")` then
  `metric.compute(...)` is the standard scoring pass of every `transformers`
  fine-tune written since 2022, including the one in the labelled corpus.
* **torchmetrics objects.** `knowledge._PREFIX_RULES` already lands a
  `torchmetrics.` constructor in the Evaluate lane, but the object it produced
  carried **no receiver family**, so `acc.update(...)` / `acc.compute()` - the
  entire point of a metric object - resolved to nothing.

Roles: `TS_MODEL` / `TS_FIT` are new and **no rule keys on them**. The
semantically tempting move is to give `SARIMAX.fit` the `FIT` role, which is
what MLV101 and MLV102 watch; that is a rule decision with a precision cost on
a corpus nobody has measured yet, so this table draws the box and leaves the
judgement to whoever measures it. `predict` / `forecast` do take the existing
`PREDICT` role: it is the same claim sklearn's `predict` already makes.

Framework values are `Framework` enum members or nothing: statsmodels and
Prophet are not in the enum (`contracts/graph.schema.json`), so they are
`other`, which is what the enum's last member is for.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

__all__ = ["STATS", "STATS_METHODS", "STATS_FAMILY_BASE"]

O = "other"
HF = "hf"
TM = "torchmetrics"

STATS: Dict[str, Entry] = {}
STATS_METHODS: Dict[str, Entry] = {}

# ----------------------------------------------------------- statsmodels ----
_TS_MODEL = E("model", "model", O, "TS_MODEL", ("MODEL",), "statsmodel")

for _mod in ("statsmodels.api", "statsmodels.regression.linear_model",
             "statsmodels.discrete.discrete_model"):
    STATS.update(expand(_mod, ["OLS", "WLS", "GLS", "GLM", "Logit", "Probit",
                               "MNLogit", "Poisson", "QuantReg", "MixedLM",
                               "RLM"], _TS_MODEL))
for _mod in ("statsmodels.tsa.arima.model", "statsmodels.tsa.api",
             "statsmodels.api.tsa"):
    STATS.update(expand(_mod, ["ARIMA", "SARIMAX", "AutoReg", "VAR", "VARMAX",
                               "ExponentialSmoothing", "SimpleExpSmoothing",
                               "Holt", "UnobservedComponents", "STL",
                               "seasonal_decompose"], _TS_MODEL))
STATS["statsmodels.tsa.statespace.sarimax.SARIMAX"] = dict(_TS_MODEL)
STATS["statsmodels.tsa.holtwinters.ExponentialSmoothing"] = dict(_TS_MODEL)
STATS.update(expand("statsmodels.formula.api", ["ols", "logit", "glm", "mixedlm"],
                    _TS_MODEL))

# ---------------------------------------------------------------- Prophet ----
for _root in ("prophet", "fbprophet"):
    STATS["%s.Prophet" % _root] = E("model", "model", O, "TS_MODEL", ("MODEL",),
                                    "prophet")

STATS_METHODS.update({
    # The results object keeps the family, which is what makes the second hop
    # (`res.forecast(...)`) resolve at all.
    "statsmodels.base.model.Model.fit": E("model", "train", O, "TS_FIT",
                                          ("MODEL",), "statsmodel"),
    "statsmodels.base.model.Model.fit_regularized": E("model", "train", O, "TS_FIT",
                                                      ("MODEL",), "statsmodel"),
    "statsmodels.base.model.Model.predict": E("predict", "eval", O, "PREDICT",
                                              ("PREDS",), "statsmodel"),
    "statsmodels.base.model.Model.forecast": E("predict", "eval", O, "PREDICT",
                                               ("PREDS",), "statsmodel"),
    "statsmodels.base.model.Model.get_forecast": E("predict", "eval", O, "PREDICT",
                                                   ("PREDS",), "statsmodel"),
    "statsmodels.base.model.Model.get_prediction": E("predict", "eval", O, "PREDICT",
                                                     ("PREDS",), "statsmodel"),
    "statsmodels.base.model.Model.summary": E("model", "model", O, "MODEL_SUMMARY",
                                              (), "statsmodel", 0.3),
    "prophet.Prophet.fit": E("model", "train", O, "TS_FIT", ("MODEL",), "prophet"),
    "prophet.Prophet.predict": E("predict", "eval", O, "PREDICT", ("PREDS",),
                                 "prophet"),
    "prophet.Prophet.make_future_dataframe": E("transform", "preprocess", O,
                                               "FRAME_TEMPORAL", (), "frame"),
    "prophet.Prophet.add_regressor": E("config", "model", O, "TS_MODEL", (),
                                       "prophet", 0.4),
    "prophet.Prophet.add_seasonality": E("config", "model", O, "TS_MODEL", (),
                                         "prophet", 0.4),
})

# ------------------------------------------------------- HuggingFace eval ----
STATS["evaluate.load"] = E("metric", "eval", HF, "HF_METRIC", (), "hf_metric")
STATS["evaluate.combine"] = E("metric", "eval", HF, "HF_METRIC", (), "hf_metric")
STATS["evaluate.evaluator"] = E("metric", "eval", HF, "HF_METRIC", (), "hf_metric")
STATS_METHODS.update({
    "evaluate.EvaluationModule.compute": E("metric", "eval", HF, "METRIC"),
    "evaluate.EvaluationModule.add": E("metric", "eval", HF, "METRIC_UPDATE", (),
                                       "hf_metric", 0.4),
    "evaluate.EvaluationModule.add_batch": E("metric", "eval", HF, "METRIC_UPDATE",
                                             (), "hf_metric", 0.4),
})

# ---------------------------------------------------------- torchmetrics ----
STATS_METHODS.update({
    "torchmetrics.Metric.update": E("metric", "eval", TM, "METRIC_UPDATE", (),
                                    "torchmetric", 0.4),
    "torchmetrics.Metric.compute": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.forward": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.__call__": E("metric", "eval", TM, "METRIC"),
    "torchmetrics.Metric.reset": E("metric", "eval", TM, "METRIC_UPDATE", (),
                                   "torchmetric", 0.2),
    "torchmetrics.Metric.to": E("metric", "eval", TM, "TO_DEVICE", (), "torchmetric"),
})

#: Receiver-family bases contributed to `ir/resolve_receivers._FAMILY_BASE`.
STATS_FAMILY_BASE: Dict[str, str] = {
    "statsmodel": "statsmodels.base.model.Model",
    "prophet": "prophet.Prophet",
    "hf_metric": "evaluate.EvaluationModule",
    "torchmetric": "torchmetrics.Metric",
}
