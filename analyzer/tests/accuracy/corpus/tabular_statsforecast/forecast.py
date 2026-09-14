"""Classical forecasting: SARIMAX and Prophet on the same weekly series.

Both models are fitted on the past and scored on the future - the cut is by
timestamp, never by a random draw - and Prophet's own rolling-origin
cross-validation is used rather than a k-fold that would train on later weeks
than it scores.

Nothing here is a scikit-learn estimator, so there is no Pipeline to put a
transformer in; the Box-Cox transform is fitted on the training window only and
the same lambda is used to invert the forecast.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics
from scipy.stats import boxcox
from sklearn.metrics import mean_absolute_percentage_error
from statsmodels.tsa.statespace.sarimax import SARIMAX

HOLDOUT_WEEKS = 26
ORDER = (1, 1, 1)
SEASONAL_ORDER = (0, 1, 1, 52)


def load_series(csv_path: str) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, parse_dates=["week_start"])
    frame = frame.sort_values("week_start").reset_index(drop=True)
    frame = frame.set_index("week_start").asfreq("W-MON")
    return frame


def split_by_time(frame: pd.DataFrame):
    cutoff = frame.index[-HOLDOUT_WEEKS]
    history = frame.loc[frame.index < cutoff]
    future = frame.loc[frame.index >= cutoff]
    return history, future


def fit_sarimax(history: pd.DataFrame):
    transformed, lam = boxcox(history["units"].clip(lower=1.0))
    endog = pd.Series(transformed, index=history.index)
    model = SARIMAX(endog, order=ORDER, seasonal_order=SEASONAL_ORDER,
                    enforce_stationarity=False, enforce_invertibility=False)
    return model.fit(disp=False), lam


def score_sarimax(fitted, lam: float, future: pd.DataFrame) -> float:
    forecast = fitted.forecast(steps=len(future))
    restored = np.power(np.maximum(forecast * lam + 1.0, 1e-6), 1.0 / lam)
    return float(mean_absolute_percentage_error(future["units"], restored))


def decompose(history: pd.DataFrame):
    return sm.tsa.seasonal_decompose(history["units"], model="additive", period=52)


def fit_prophet(history: pd.DataFrame) -> Prophet:
    frame = history.reset_index().rename(columns={"week_start": "ds",
                                                  "units": "y"})
    model = Prophet(weekly_seasonality=False, yearly_seasonality=True,
                    changepoint_prior_scale=0.05, interval_width=0.8)
    model.add_country_holidays(country_name="US")
    model.fit(frame)
    return model


def rolling_origin_cv(model: Prophet) -> pd.DataFrame:
    folds = cross_validation(model, initial="730 days", period="91 days",
                             horizon="182 days")
    return performance_metrics(folds)


def main(csv_path: str = "data/weekly_units.csv") -> dict:
    frame = load_series(csv_path)
    history, future = split_by_time(frame)

    fitted, lam = fit_sarimax(history)
    sarimax_mape = score_sarimax(fitted, lam, future)

    prophet = fit_prophet(history)
    metrics = rolling_origin_cv(prophet)

    return {"sarimax_mape": sarimax_mape,
            "prophet_mape": float(metrics["mape"].mean()),
            "trend_strength": float(decompose(history).trend.std())}


if __name__ == "__main__":
    print(main())
