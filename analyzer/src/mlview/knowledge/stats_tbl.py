"""Classical statistics / forecasting knowledge — TAB-01, TAB-12.

**Why this file exists.** `knowledge.role_of` returned `None` for
`statsmodels.tsa.statespace.sarimax.SARIMAX`, `prophet.Prophet`,
`scipy.stats.boxcox`, `statsmodels.api.tsa.seasonal_decompose` and
`prophet.diagnostics.cross_validation`. Those FQNs *resolve* through the import
table, so `ir/resolve.py` never set `unresolved_callee` and `core/unresolved.py`
emitted no diagnostic: the calls were dropped from the graph with nothing said.

On `analyzer/tests/accuracy/corpus/tabular_statsforecast/forecast.py` — 90
lines, two fitted models, a Box-Cox transform, a seasonal decomposition and a
rolling-origin cross-validation — MLView drew 11 nodes, recovered 2 of 13
hand-drawn ops (the worst score in the corpus) and stated
`not detected: preprocess, model, objective, deliver` with
`graph.diagnostics == []`. README requirement 1 promises the opposite: stages
that are absent are **declared**, not dropped — and here a present stage was
declared absent with nothing to qualify it.

The same silence covered five sklearn holes (`TSNE`,
`CalibratedClassifierCV`, `calibration_curve`, `GaussianMixture`,
`TransformedTargetRegressor`), which are listed here beside the forecasting
rows because they are the same defect: a resolved FQN with no row.

Everything maps onto existing roles and onto the `sklearn` / `other`
`Framework` enum values; nothing in `contracts/graph.schema.json` changes.
"""

from __future__ import annotations

from typing import Dict

from .entries import E, Entry, expand

S = "sklearn"
O = "other"

STATS: Dict[str, Entry] = {}

# ----------------------------------------------------------- statsmodels ---
#: A `SARIMAX(...)` / `ARIMA(...)` object is the model; `.fit()` on it is the
#: training call, and `.forecast()` / `.get_forecast()` / `.predict()` are the
#: prediction calls. Roots are listed both as the public `statsmodels.api.*`
#: alias and as the long module path, because real code writes either.
_SARIMAX_ROOTS = (
    "statsmodels.tsa.statespace.sarimax",
    "statsmodels.api.tsa.statespace",
    "statsmodels.tsa.api",
    "statsmodels.api.tsa",
)
for _root in _SARIMAX_ROOTS:
    STATS.update(expand(_root, [
        "SARIMAX", "ARIMA", "ARMA", "AutoReg", "VAR", "VARMAX",
        "ExponentialSmoothing", "SimpleExpSmoothing", "Holt", "UnobservedComponents",
    ], E("model", "model", O, "ESTIMATOR", ("MODEL",), "statsmodel")))
for _root in ("statsmodels.api", "statsmodels.regression.linear_model"):
    STATS.update(expand(_root, ["OLS", "WLS", "GLS", "GLM", "Logit", "Probit",
                                "QuantReg", "MixedLM"],
                        E("model", "model", O, "ESTIMATOR", ("MODEL",), "statsmodel")))
for _root in ("statsmodels.tsa.seasonal", "statsmodels.api.tsa", "statsmodels.tsa.api"):
    STATS["%s.seasonal_decompose" % _root] = E("transform", "preprocess", O, "TRANSFORM")
    STATS["%s.STL" % _root] = E("transform", "preprocess", O, "TRANSFORM")
for _root in ("statsmodels.tsa.stattools", "statsmodels.api.tsa", "statsmodels.tsa.api"):
    STATS["%s.adfuller" % _root] = E("metric", "eval", O, "METRIC")
    STATS["%s.acf" % _root] = E("metric", "eval", O, "METRIC")
    STATS["%s.pacf" % _root] = E("metric", "eval", O, "METRIC")

STATS_METHODS: Dict[str, Entry] = {}
for _root in _SARIMAX_ROOTS + ("statsmodels.api", "statsmodels.regression.linear_model"):
    for _cls in ("SARIMAX", "ARIMA", "ExponentialSmoothing", "OLS", "AutoReg", "VAR"):
        _base = "%s.%s" % (_root, _cls)
        STATS_METHODS["%s.fit" % _base] = E("model", "train", O, "FIT")
        STATS_METHODS["%s.forecast" % _base] = E("predict", "eval", O, "PREDICT", ("PREDS",))
        STATS_METHODS["%s.predict" % _base] = E("predict", "eval", O, "PREDICT", ("PREDS",))
        STATS_METHODS["%s.get_forecast" % _base] = E("predict", "eval", O, "PREDICT",
                                                     ("PREDS",))
        STATS_METHODS["%s.summary" % _base] = E("metric", "eval", O, "METRIC", (), None, 0.5)

# --------------------------------------------------------------- prophet ---
for _root in ("prophet", "fbprophet"):
    STATS["%s.Prophet" % _root] = E("model", "model", O, "ESTIMATOR", ("MODEL",),
                                    "prophet")
    STATS["%s.diagnostics.cross_validation" % _root] = E("metric", "eval", O, "CV")
    STATS["%s.diagnostics.performance_metrics" % _root] = E("metric", "eval", O, "METRIC")
    STATS["%s.serialize.model_to_json" % _root] = E("checkpoint", "deliver", O, "SAVE")
    STATS["%s.serialize.model_from_json" % _root] = E("checkpoint", "deliver", O, "LOAD")
    STATS_METHODS["%s.Prophet.fit" % _root] = E("model", "train", O, "FIT")
    STATS_METHODS["%s.Prophet.predict" % _root] = E("predict", "eval", O, "PREDICT",
                                                    ("PREDS",))
    STATS_METHODS["%s.Prophet.make_future_dataframe" % _root] = E(
        "transform", "preprocess", O, "TRANSFORM")
    STATS_METHODS["%s.Prophet.add_country_holidays" % _root] = E(
        "config", "config", O, "CONFIG_ARG", (), None, 0.5)
    STATS_METHODS["%s.Prophet.add_regressor" % _root] = E(
        "config", "config", O, "CONFIG_ARG", (), None, 0.5)

#: The family base `ir/resolve._FAMILY_BASE` maps `statsmodel` onto, so
#: `model = SARIMAX(...); model.fit()` resolves through the family as well as
#: through the producer's own FQN.
for _method, _row in (("fit", E("model", "train", O, "FIT")),
                      ("forecast", E("predict", "eval", O, "PREDICT", ("PREDS",))),
                      ("predict", E("predict", "eval", O, "PREDICT", ("PREDS",))),
                      ("get_forecast", E("predict", "eval", O, "PREDICT", ("PREDS",))),
                      ("summary", E("metric", "eval", O, "METRIC", (), None, 0.5))):
    STATS_METHODS["statsmodels.api.SARIMAX.%s" % _method] = dict(_row)


# ----------------------------------------------------------------- scipy ---
#: A Box-Cox / Yeo-Johnson transform is preprocessing in exactly the sense
#: MLV101 cares about: it learns a parameter from the rows it is given.
STATS.update(expand("scipy.stats", ["boxcox", "yeojohnson", "zscore"],
                    E("transform", "preprocess", O, "TRANSFORM")))
STATS["scipy.special.inv_boxcox"] = E("transform", "preprocess", O, "TRANSFORM")

# --------------------------------------------------- sklearn holes (TAB-01) -
STATS["sklearn.manifold.TSNE"] = E("transform", "preprocess", S, "TRANSFORMER", (),
                                   "estimator")
STATS["sklearn.manifold.Isomap"] = E("transform", "preprocess", S, "TRANSFORMER", (),
                                     "estimator")
STATS["sklearn.calibration.CalibratedClassifierCV"] = E("model", "model", S, "ESTIMATOR",
                                                        ("MODEL",), "estimator")
STATS["sklearn.calibration.calibration_curve"] = E("metric", "eval", S, "METRIC")
STATS["sklearn.mixture.GaussianMixture"] = E("model", "model", S, "ESTIMATOR",
                                             ("MODEL",), "estimator")
STATS["sklearn.mixture.BayesianGaussianMixture"] = E("model", "model", S, "ESTIMATOR",
                                                     ("MODEL",), "estimator")
STATS["sklearn.compose.TransformedTargetRegressor"] = E("model", "model", S, "ESTIMATOR",
                                                        ("MODEL",), "estimator")
STATS["sklearn.inspection.permutation_importance"] = E("metric", "eval", S, "METRIC")
STATS["sklearn.inspection.PartialDependenceDisplay"] = E("metric", "eval", S, "METRIC")
