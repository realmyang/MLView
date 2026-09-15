"""GRAPH-R2: forecasting estimators and metric objects.

A statsmodels / Prophet script has no `nn.Module`, no sklearn estimator and no
`fit` / `predict` the tables recognised, so its Model, Train and Evaluate lanes
were empty. `evaluate.load(...)` / `.compute(...)` is the scoring pass of every
`transformers` fine-tune, and a torchmetrics object with no receiver family
answered nothing for the `update` / `compute` pair that is its entire purpose.
"""
from __future__ import annotations

import evaluate
import statsmodels.api as sm
import torchmetrics
from prophet import Prophet
from statsmodels.tsa.statespace.sarimax import SARIMAX


def arima_forecast(series, horizon: int = 24):
    model = SARIMAX(series, order=(1, 1, 1))
    fitted = model.fit(disp=False)
    return fitted.forecast(horizon)


def ols_fit(features, target):
    model = sm.OLS(target, features)
    result = model.fit()
    return result.predict(features)


def prophet_forecast(frame, periods: int = 30):
    model = Prophet()
    model.fit(frame)
    future = model.make_future_dataframe(periods=periods)
    return model.predict(future)


def hf_score(predictions, references):
    metric = evaluate.load("accuracy")
    metric.add_batch(predictions=predictions, references=references)
    return metric.compute()


def torch_score(preds, target):
    accuracy = torchmetrics.Accuracy(task="multiclass", num_classes=10)
    accuracy.update(preds, target)
    return accuracy.compute()
