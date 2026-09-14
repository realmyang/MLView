"""Gradient-boosting estimators: xgboost, lightgbm, catboost (FW-RECOG).

The Sprint-3 audit's finding was that xgboost was *detected as a framework*
(`knowledge._MODULE_FRAMEWORK` lists it) and then had **no entries at all**, so
`xgb.XGBClassifier(...)`, `model.fit(...)` and `model.predict_proba(...)` were
either invisible or attributed to sklearn.

Two shapes:

* the estimators carry the **`estimator` family**, because they really do
  implement the scikit-learn estimator protocol - that is what makes
  `sklearn.base.BaseEstimator.*` a legitimate fallback for a method nobody
  listed here;
* the four methods the audit named - `fit`, `predict`, `predict_proba` and
  `score` - are registered **per estimator FQN** as well, because
  `ir/resolve._canonical_for_receiver` proposes `<producer FQN>.<method>` first
  and an exact hit there attributes the node to xgboost / lightgbm rather than
  to sklearn. `fit` keeps the real `FIT` role, so MLV101 sees a boosting model
  fitted before the split exactly as it sees an sklearn one.

`xgboost.train` / `lightgbm.train` deliberately use `GBM_TRAIN` rather than
`FIT`: their first positional argument is the parameter dict, and
`core/coverage.UNTRACED_ROLES` reads argument 0 of every `FIT` site, so the
role would put a "could not trace this value" note on correct code.

catboost is not a value of the frozen `Framework` enum (CONTRACTS section 1),
so its rows are attributed to `other` rather than inventing an enum member.
"""

from __future__ import annotations

from typing import Dict, Tuple

from .entries import E, Entry, expand

__all__ = ["GBM", "GBM_METHODS"]

XGB, LGBM, OTHER_FW = "xgboost", "lightgbm", "other"

#: (module, framework, estimator class names)
_ESTIMATORS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("xgboost", XGB, ("XGBClassifier", "XGBRegressor", "XGBRanker",
                      "XGBRFClassifier", "XGBRFRegressor", "XGBModel")),
    ("lightgbm", LGBM, ("LGBMClassifier", "LGBMRegressor", "LGBMRanker", "LGBMModel")),
    ("catboost", OTHER_FW, ("CatBoostClassifier", "CatBoostRegressor", "CatBoost")),
)

GBM: Dict[str, Entry] = {}
GBM_METHODS: Dict[str, Entry] = {}

for _module, _fw, _names in _ESTIMATORS:
    GBM.update(expand(_module, _names,
                      E("model", "model", _fw, "ESTIMATOR", ("MODEL",), "estimator")))

#: The matrix / pool wrappers a boosting library wants its data in.
GBM["xgboost.DMatrix"] = E("dataset", "data", XGB, "DATASET", ("RAW_DATA",), "dmatrix")
GBM["xgboost.QuantileDMatrix"] = E("dataset", "data", XGB, "DATASET", ("RAW_DATA",),
                                   "dmatrix")
GBM["xgboost.DeviceQuantileDMatrix"] = E("dataset", "data", XGB, "DATASET",
                                         ("RAW_DATA",), "dmatrix")
GBM["lightgbm.Dataset"] = E("dataset", "data", LGBM, "DATASET", ("RAW_DATA",), "dmatrix")
GBM["catboost.Pool"] = E("dataset", "data", OTHER_FW, "DATASET", ("RAW_DATA",), "dmatrix")

#: PUB2-08. The native Booster - what `xgb.train(...)` / `lgb.train(...)` hand
#: back, and the spelling every demo in both repositories uses. There was no
#: constructor row for it and `xgboost.train` declared no return type, so `bst`
#: never acquired the family, `_canonical_for_receiver` proposed
#: `xgboost.train.predict`, and the four `*.Booster.*` method rows below were
#: **unreachable code**. Measured on `xgboost/demo/multiclass_classification/
#: train.py` - 22 lines, `DMatrix` -> `train` -> `predict` -> an error rate ->
#: `save_model`: 5 nodes, 2 edges, stages present `data, train`, `not detected:
#: model, objective, eval, deliver`, `diagnostics: []`, and an answer card
#: reading "No evaluation stage was detected: nothing computes a metric or runs
#: the model in eval mode" plus "No findings: no rule fired on this workspace".
#: Three stages claimed absent, three calls dropped, and a clean bill of health.
GBM["xgboost.Booster"] = E("model", "model", XGB, "ESTIMATOR", ("MODEL",),
                           "xgb_booster")
GBM["lightgbm.Booster"] = E("model", "model", LGBM, "ESTIMATOR", ("MODEL",),
                            "lgb_booster")

#: The functional training entry points. The `family` is what gives `bst` the
#: Booster receiver family without the author having to annotate it.
GBM["xgboost.train"] = E("train_loop", "train", XGB, "GBM_TRAIN", ("MODEL",),
                         "xgb_booster")
GBM["lightgbm.train"] = E("train_loop", "train", LGBM, "GBM_TRAIN", ("MODEL",),
                          "lgb_booster")
GBM["xgboost.cv"] = E("metric", "eval", XGB, "CV")
GBM["lightgbm.cv"] = E("metric", "eval", LGBM, "CV")
GBM["xgboost.plot_importance"] = E("metric", "eval", XGB, "METRIC", (), None, 0.5)
GBM["lightgbm.plot_importance"] = E("metric", "eval", LGBM, "METRIC", (), None, 0.5)

#: The estimator protocol, per estimator FQN, so the node is attributed to the
#: boosting library rather than to the sklearn base it falls back on.
_PROTOCOL = (
    ("fit", lambda fw: E("train_loop", "train", fw, "FIT")),
    ("predict", lambda fw: E("predict", "eval", fw, "PREDICT", ("PREDS",))),
    ("predict_proba", lambda fw: E("predict", "eval", fw, "PREDICT", ("PROBS",))),
    ("score", lambda fw: E("metric", "eval", fw, "METRIC")),
    ("save_model", lambda fw: E("checkpoint", "deliver", fw, "SAVE")),
    ("load_model", lambda fw: E("checkpoint", "deliver", fw, "LOAD")),
    ("get_booster", lambda fw: E("model", "model", fw, "ESTIMATOR", ("MODEL",),
                                 "estimator")),
)
for _module, _fw, _names in _ESTIMATORS:
    for _name in _names:
        for _method, _make in _PROTOCOL:
            GBM_METHODS["%s.%s.%s" % (_module, _name, _method)] = _make(_fw)

#: Booster objects returned by the functional API - the whole native protocol,
#: not only the two rows that used to be here and were unreachable (PUB2-08).
#: NB the native `Booster.predict` returns the **margin or probability**, not a
#: class - unlike the sklearn-wrapper `.predict` above, which returns labels.
#: Tagging it PREDS made MLV306 ("ranking metric fed hard labels") fire at 0.90
#: on `float(roc_auc_score(test_y, booster.predict(dtest)))`, which is the
#: textbook-correct way to score a booster.
_BOOSTER_PROTOCOL = (
    ("predict", lambda fw: E("predict", "eval", fw, "PREDICT", ("PROBS",))),
    ("inplace_predict", lambda fw: E("predict", "eval", fw, "PREDICT", ("PROBS",))),
    ("save_model", lambda fw: E("checkpoint", "deliver", fw, "SAVE")),
    ("load_model", lambda fw: E("checkpoint", "deliver", fw, "LOAD")),
    ("save_raw", lambda fw: E("checkpoint", "deliver", fw, "SAVE")),
    ("dump_model", lambda fw: E("checkpoint", "deliver", fw, "SAVE")),
    ("eval", lambda fw: E("metric", "eval", fw, "METRIC")),
    ("eval_set", lambda fw: E("metric", "eval", fw, "METRIC")),
    ("update", lambda fw: E("train_loop", "train", fw, "GBM_TRAIN")),
    ("get_score", lambda fw: E("metric", "eval", fw, "METRIC", (), None, 0.6)),
    ("best_iteration", lambda fw: E("metric", "eval", fw, "METRIC", (), None, 0.4)),
    ("trees_to_dataframe", lambda fw: E("metric", "eval", fw, "METRIC", (), None, 0.4)),
)
for _module, _fw in (("xgboost", XGB), ("lightgbm", LGBM)):
    for _method, _make in _BOOSTER_PROTOCOL:
        GBM_METHODS["%s.Booster.%s" % (_module, _method)] = _make(_fw)
