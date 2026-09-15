"""Time-to-event modelling: a Cox model and a random survival forest.

Survival analysis is a shape every generic ML linter gets wrong, because the
target is two columns rather than one and "the label" is a structured array.
Everything here is correct:

* the frame is split once, stratified on the event indicator, with a
  `random_state=`;
* the Cox model is fitted on the training frame, which for `lifelines` means
  handing it the covariates *and* the duration and event columns together -
  that is the API, not a target leaking into the feature matrix;
* the imputer and the scaler are `Pipeline` steps of the forest, so they refit
  per fold inside `cross_val_score`;
* the held-out frame is scored once, by `predict_partial_hazard` and
  `predict`, and never fitted on.

`lifelines` and `scikit-survival` are also a deliberate probe of what MLView
says about a workspace built on libraries it has no knowledge table for.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.utils import concordance_index
from sklearn.impute import SimpleImputer
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sksurv.ensemble import RandomSurvivalForest
from sksurv.metrics import concordance_index_censored

SEED = 300
DURATION = "months_observed"
EVENT = "relapsed"
COVARIATES = ["age", "tumour_size_mm", "nodes_positive", "grade",
              "hormone_therapy", "biomarker_score"]


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)


def load(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    frame = frame.dropna(subset=[DURATION, EVENT])
    frame[EVENT] = frame[EVENT].astype(bool)
    return frame


def split(frame: pd.DataFrame):
    return train_test_split(frame, test_size=0.25, stratify=frame[EVENT],
                            random_state=SEED)


def structured_target(frame: pd.DataFrame) -> np.ndarray:
    """The `(event, time)` record array scikit-survival expects."""
    return np.array(list(zip(frame[EVENT].to_numpy(), frame[DURATION].to_numpy())),
                    dtype=[("event", bool), ("time", float)])


def fit_cox(train_frame: pd.DataFrame) -> CoxPHFitter:
    columns = COVARIATES + [DURATION, EVENT]
    cox = CoxPHFitter(penalizer=0.05)
    cox.fit(train_frame[columns], duration_col=DURATION, event_col=EVENT)
    return cox


def baseline_survival(train_frame: pd.DataFrame) -> KaplanMeierFitter:
    kaplan = KaplanMeierFitter()
    kaplan.fit(train_frame[DURATION], event_observed=train_frame[EVENT])
    return kaplan


def build_forest() -> Pipeline:
    return Pipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("rsf", RandomSurvivalForest(n_estimators=300, min_samples_leaf=15,
                                     n_jobs=-1, random_state=SEED)),
    ])


def cross_validate_forest(train_frame: pd.DataFrame) -> float:
    folds = KFold(n_splits=5, shuffle=True, random_state=SEED)
    scores = cross_val_score(build_forest(), train_frame[COVARIATES],
                             structured_target(train_frame), cv=folds)
    return float(np.mean(scores))


def evaluate(cox, forest, test_frame: pd.DataFrame) -> dict:
    risk = cox.predict_partial_hazard(test_frame[COVARIATES])
    cox_ci = concordance_index(test_frame[DURATION], -risk, test_frame[EVENT])

    forest_risk = forest.predict(test_frame[COVARIATES])
    forest_ci = concordance_index_censored(test_frame[EVENT].to_numpy(),
                                           test_frame[DURATION].to_numpy(),
                                           forest_risk)
    return {"cox_concordance": float(cox_ci),
            "forest_concordance": float(forest_ci[0])}


def main(csv_path: str = "data/relapse.csv") -> dict:
    seed_everything()
    frame = load(csv_path)
    train_frame, test_frame = split(frame)

    cox = fit_cox(train_frame)
    kaplan = baseline_survival(train_frame)

    forest = build_forest()
    forest.fit(train_frame[COVARIATES], structured_target(train_frame))

    report = evaluate(cox, forest, test_frame)
    report["cv_concordance"] = cross_validate_forest(train_frame)
    report["median_survival_months"] = float(kaplan.median_survival_time_)
    return report


if __name__ == "__main__":
    print(main())
