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

#: The functional training entry points.
GBM["xgboost.train"] = E("train_loop", "train", XGB, "GBM_TRAIN")
GBM["lightgbm.train"] = E("train_loop", "train", LGBM, "GBM_TRAIN")
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

#: Booster objects returned by the functional API.
GBM_METHODS["xgboost.Booster.predict"] = E("predict", "eval", XGB, "PREDICT", ("PREDS",))
GBM_METHODS["xgboost.Booster.save_model"] = E("checkpoint", "deliver", XGB, "SAVE")
GBM_METHODS["lightgbm.Booster.predict"] = E("predict", "eval", LGBM, "PREDICT",
                                            ("PREDS",))
GBM_METHODS["lightgbm.Booster.save_model"] = E("checkpoint", "deliver", LGBM, "SAVE")
