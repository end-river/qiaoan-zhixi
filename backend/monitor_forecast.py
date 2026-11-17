import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from .monitor_data import time_string


def naive(series, steps):
    values = np.repeat(float(series[-1]), steps)
    width = (
        norm.ppf(0.975)
        * np.std(np.diff(series), ddof=1)
        * np.sqrt(np.arange(1, steps + 1))
    )
    return values, values - width, values + width


def sarimax(series, steps):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        fitted = SARIMAX(series, order=(1, 1, 0)).fit(disp=False, maxiter=50)
    if not fitted.mle_retvals["converged"]:
        raise ValueError("SARIMAX 未收敛")
    forecast = fitted.get_forecast(steps=steps)
    values = np.asarray(forecast.predicted_mean)
    ranges = np.asarray(forecast.conf_int(alpha=0.05))
    if not np.isfinite(values).all() or not np.isfinite(ranges).all():
        raise ValueError("SARIMAX 未返回有限预测值")
    return values, ranges[:, 0], ranges[:, 1]


def forecast(series, interval, steps, check):
    n = len(series)
    if n < 60:
        raise ValueError("预测至少需要 60 个有效、等间隔的原始采样点")
    horizon = steps if steps is not None else min(24, max(1, n // 10))
    if not 1 <= horizon <= min(24, (n - 30) // 3):
        raise ValueError(
            f"当前数据可预测 1 至 {min(24, (n - 30) // 3)} 步，并保留三段回测"
        )
    values = series.to_numpy()
    metrics, results = [], {}
    for label, method in (("末值基准", naive), ("SARIMAX(1,1,0)", sarimax)):
        records = []
        try:
            for i in range(3, 0, -1):
                check()
                cutoff = n - i * horizon
                predictions, low, high = method(values[:cutoff], horizon)
                for offset in range(horizon):
                    j = cutoff + offset
                    records.append(
                        {
                            "时间": time_string(series.index[j]),
                            "训练截止": time_string(series.index[cutoff - 1]),
                            "实测": float(values[j]),
                            "回测预测": float(predictions[offset]),
                            "下界": float(low[offset]),
                            "上界": float(high[offset]),
                        }
                    )
            check()
            future = method(values, horizon)
        except (ValueError, np.linalg.LinAlgError) as exc:
            metrics.append({"模型": label, "MAE": None, "RMSE": None, "说明": str(exc)})
            continue
        error = np.array([row["实测"] - row["回测预测"] for row in records])
        metrics.append(
            {
                "模型": label,
                "MAE": float(np.abs(error).mean()),
                "RMSE": float(np.sqrt(np.square(error).mean())),
            }
        )
        results[label] = (records, future)
    best = min(
        (row for row in metrics if row["MAE"] is not None), key=lambda row: row["MAE"]
    )
    backtest, (central, lower, upper) = results[best["模型"]]
    future_index = series.index[-1] + pd.to_timedelta(
        np.arange(1, horizon + 1) * interval, unit="s"
    )
    rows = [
        {"时间": time_string(t), "预测": float(m), "下界": float(lo), "上界": float(hi)}
        for t, m, lo, hi in zip(future_index, central, lower, upper)
    ]
    return best, metrics, backtest, rows
