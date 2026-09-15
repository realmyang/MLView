"""The `promote_if_better` task. Registry bookkeeping, no ML.

It reads the metrics the evaluate task wrote, compares them with the currently
promoted model's, and copies the artefact into the `production` slot. There is
no model call, no fit and no data here; the whole file is a guard that MLView
does not invent a training or evaluation stage out of file copies.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

MODEL_ROOT = Path("/opt/airflow/models/churn")
METRIC_ROOT = Path("/opt/airflow/metrics/churn")
PRODUCTION = MODEL_ROOT / "production.joblib"
PRODUCTION_METRICS = METRIC_ROOT / "production.json"


def _current_auc() -> float:
    if not PRODUCTION_METRICS.exists():
        return 0.0
    return float(json.loads(PRODUCTION_METRICS.read_text()).get("auc", 0.0))


def promote_if_better(snapshot: str, min_auc: float) -> bool:
    candidate_metrics = json.loads(
        (METRIC_ROOT / ("%s.json" % snapshot)).read_text())
    candidate_auc = float(candidate_metrics["auc"])

    if candidate_auc < min_auc:
        print("candidate auc %.4f below the floor %.4f" % (candidate_auc, min_auc))
        return False
    if candidate_auc <= _current_auc():
        print("candidate auc %.4f does not beat production" % candidate_auc)
        return False

    shutil.copyfile(MODEL_ROOT / ("%s.joblib" % snapshot), PRODUCTION)
    PRODUCTION_METRICS.write_text(json.dumps(candidate_metrics))
    print("promoted %s at auc %.4f" % (snapshot, candidate_auc))
    return True
