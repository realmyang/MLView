"""An Optuna sweep over XGBoost's native API, tuned on the test set.

Planted defects, in the order they appear:

* the quantile transform is fitted on the whole feature matrix before any split
  exists, so every quantile boundary the model trains against was computed with
  the held-out rows in it;
* the split carries no `random_state=` and nothing seeds `random`, numpy or the
  Optuna sampler, so neither the split nor the search is reproducible;
* every trial's `evals` watch-list is the *test* `DMatrix` and every trial stops
  early on it - two hundred trials of early stopping against the data the final
  number is reported from;
* the objective *returns* the test AUC, so the search maximises the number that
  is afterwards presented as an unbiased estimate;
* `xgb.cv` is then run over the already-transformed whole matrix, so no fold
  refits the transform;
* the final report computes accuracy from a probability column and AUC from
  hard labels.
"""
from __future__ import annotations

import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import QuantileTransformer
from xgboost import XGBClassifier

TARGET = "default_next_month"
N_TRIALS = 200


def prepare(csv_path: str):
    frame = pd.read_csv(csv_path)

    labels = frame[TARGET]
    features = frame.drop(columns=[TARGET])

    quantiles = QuantileTransformer(output_distribution="normal",
                                    n_quantiles=1000)
    features = quantiles.fit_transform(features)

    train_x, test_x, train_y, test_y = train_test_split(features, labels,
                                                        test_size=0.2)
    return train_x, test_x, train_y, test_y, features, labels


def search_space(trial) -> dict:
    return {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": trial.suggest_int("max_depth", 3, 12),
        "eta": trial.suggest_float("eta", 0.005, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
        "min_child_weight": trial.suggest_float("min_child_weight", 1.0, 50.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 50.0, log=True),
    }


def make_objective(dtrain, dtest, test_y):
    def objective(trial) -> float:
        params = search_space(trial)
        booster = xgb.train(params, dtrain, num_boost_round=5000,
                            evals=[(dtest, "test")],
                            early_stopping_rounds=100,
                            verbose_eval=False)
        scores = booster.predict(dtest)
        return float(roc_auc_score(test_y, scores))
    return objective


def native_cv(features, labels, params: dict) -> float:
    dall = xgb.DMatrix(features, label=labels)
    history = xgb.cv(params, dall, num_boost_round=1000, nfold=5,
                     metrics=("auc",), early_stopping_rounds=50,
                     as_pandas=True)
    return float(history["test-auc-mean"].iloc[-1])


def main(csv_path: str = "data/credit.csv") -> dict:
    train_x, test_x, train_y, test_y, features, labels = prepare(csv_path)

    dtrain = xgb.DMatrix(train_x, label=train_y)
    dtest = xgb.DMatrix(test_x, label=test_y)

    study = optuna.create_study(direction="maximize")
    study.optimize(make_objective(dtrain, dtest, test_y), n_trials=N_TRIALS)

    best = dict(study.best_params)
    final = XGBClassifier(n_estimators=800, **best)
    final.fit(train_x, train_y)

    probabilities = final.predict_proba(test_x)[:, 1]
    hard_labels = final.predict(test_x)

    return {
        "roc_auc": float(roc_auc_score(test_y, hard_labels)),
        "accuracy": float(accuracy_score(test_y, probabilities)),
        "study_best_value": float(study.best_value),
        "native_cv_auc": native_cv(features, labels,
                                   {"objective": "binary:logistic",
                                    "eval_metric": "auc"}),
    }


if __name__ == "__main__":
    print(main())
