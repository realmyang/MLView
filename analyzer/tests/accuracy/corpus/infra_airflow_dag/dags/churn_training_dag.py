"""The Airflow DAG. It contains no ML code at all — only wiring.

Every task is a `PythonOperator` whose `python_callable` is a function in the
`pipelines` package. The DAG file itself never calls any of them: Airflow's
scheduler does, in a worker process, hours apart. A reader who wants to know
what this pipeline does has to follow four `python_callable=` references out of
this file, which is exactly what the graph builder has to do too.

Nothing here is a defect; `pipelines/prepare.py` is where the planted one is.
"""
from __future__ import annotations

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from pipelines.evaluate import score_holdout
from pipelines.prepare import build_features
from pipelines.promote import promote_if_better
from pipelines.train import fit_model

DEFAULT_ARGS = {
    "owner": "ml-platform",
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=10),
    "email_on_failure": True,
}

with DAG(
    dag_id="churn_training",
    description="nightly churn model refresh",
    default_args=DEFAULT_ARGS,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    schedule="0 3 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["ml", "churn"],
) as dag:

    prepare = PythonOperator(
        task_id="build_features",
        python_callable=build_features,
        op_kwargs={"snapshot": "{{ ds }}", "seed": 11},
    )

    train = PythonOperator(
        task_id="fit_model",
        python_callable=fit_model,
        op_kwargs={"snapshot": "{{ ds }}", "seed": 11},
    )

    evaluate = PythonOperator(
        task_id="score_holdout",
        python_callable=score_holdout,
        op_kwargs={"snapshot": "{{ ds }}"},
    )

    promote = PythonOperator(
        task_id="promote_if_better",
        python_callable=promote_if_better,
        op_kwargs={"snapshot": "{{ ds }}", "min_auc": 0.78},
    )

    prepare >> train >> evaluate >> promote
