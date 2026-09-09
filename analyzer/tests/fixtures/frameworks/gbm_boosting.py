"""FW-RECOG positive fixture: gradient-boosting estimators.

xgboost was *detected as a framework* and had no entries at all, so
`XGBClassifier`, `.fit`, `.predict_proba` and `DMatrix` were invisible or
attributed to sklearn. The estimators keep the sklearn `estimator` family -
they really do implement that protocol - but the four methods are registered
per estimator FQN, so the node says xgboost / lightgbm.

The split is seeded and the estimators are seeded, so this fixture is about
recognition, not about findings.
"""
from __future__ import annotations

import lightgbm as lgb
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

SEED = 7


def run(features, labels):
    train_x, test_x, train_y, test_y = train_test_split(
        features, labels, test_size=0.2, random_state=SEED)

    classifier = xgb.XGBClassifier(n_estimators=300, max_depth=6, random_state=SEED)
    classifier.fit(train_x, train_y)
    probs = classifier.predict_proba(test_x)

    regressor = lgb.LGBMRegressor(n_estimators=200, random_state=SEED)
    regressor.fit(train_x, train_y)
    preds = regressor.predict(test_x)

    classifier.save_model("out/xgb.json")
    return roc_auc_score(test_y, probs[:, 1]), preds


def run_functional(features, labels, params):
    dtrain = xgb.DMatrix(features, label=labels)
    booster = xgb.train(params, dtrain, num_boost_round=200)
    return booster.predict(dtrain)
