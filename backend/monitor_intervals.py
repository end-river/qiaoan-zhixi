"""Find observation windows that existing numerical tools can consume."""

import numpy as np

from . import monitor_data as data
from .monitor_analysis import (
    CONTINUOUS_METHODS,
    ObservationIntervalError,
    minimum_samples,
    observation_bounds,
    time_slice,
)

LIMIT = 20


def continuous_runs(ticks, usable, check):
    left = None
    step = None
    for i, keep in enumerate(usable):
        if i % 1024 == 0:
            check()
        if not keep:
            if left is not None:
                yield left, i - 1, step, False
            left = step = None
        elif left is None:
            left = i
        else:
            gap = ticks[i] - ticks[i - 1]
            if step is not None and gap != step:
                yield left, i - 1, step, True
                left = i - 1
            step = gap
    if left is not None:
        yield left, len(ticks) - 1, step, False


def scan(dataset, version, method, params, check=lambda: None):
    if method is not None and method not in CONTINUOUS_METHODS:
        raise ValueError("此工具无需扫描连续区间")
    frame = data.frame(dataset, version)
    channels = params.channels or list(frame.columns)
    if len(set(channels)) != len(channels) or any(c not in frame for c in channels):
        raise ValueError("选择的测点不存在或重复")
    if method == "lag" and len(channels) != 2:
        raise ValueError("时滞分析请选择两个测点")
    if method == "forecast" and len(channels) != 1:
        raise ValueError("请选择一个测点进行预测")

    values = time_slice(frame, params.start, params.end, allow_empty=True)[channels]
    index = values.index
    missing = values.isna().any(axis=1).to_numpy()
    duplicates = index.duplicated(keep=False)
    usable = ~(missing | duplicates)
    requires_original = method == "forecast" and bool(version["parent_id"])
    minimum = minimum_samples(method, params)
    longest = 0
    cadence_breaks = 0
    reasons = []
    candidates = []
    ticks = index.asi8
    for left, right, step, cadence_changed in continuous_runs(ticks, usable, check):
        cadence_breaks += cadence_changed
        size = right - left + 1
        longest = max(longest, size)
        if requires_original or size < minimum:
            continue
        seconds = float(step / 1e9)
        try:
            required, maximum, _ = observation_bounds(method, params, seconds)
            if size < required:
                raise ObservationIntervalError(f"区间须覆盖至少两个完整周期（{required} 个样本）")
            if method == "lag" and (values.iloc[left:right + 1].nunique() < 2).any():
                raise ObservationIntervalError("常数序列无法计算时滞相关")
        except ObservationIntervalError as exc:
            message = str(exc)
            if len(reasons) < 3 and message not in reasons:
                reasons.append(message)
            continue
        if maximum is not None and size > maximum:
            size = maximum
            left = right - size + 1
        candidates.append((size, right, left, seconds))

    if requires_original:
        reasons = ["短期趋势预测需要原始版本的连续区间。"]
    elif not len(values):
        reasons.append("扫描范围内没有观测数据。")
    elif longest < minimum:
        reasons.append(f"最长连续段有 {longest} 个样本，当前至少需要 {minimum} 个。")

    return {
        "version_id": version["id"],
        "channels": channels,
        "total_candidates": len(candidates),
        "intervals": [
            {
                "start": data.time_string(index[left]),
                "end": data.time_string(index[right]),
                "interval_seconds": seconds,
                "duration_seconds": seconds * (size - 1),
                "samples": size,
            }
            for size, right, left, seconds in sorted(candidates, reverse=True)[:LIMIT]
        ],
        "diagnostics": {
            "scanned_rows": len(values),
            "missing_rows": int(np.count_nonzero(missing)),
            "duplicate_rows": int(np.count_nonzero(duplicates)),
            "cadence_breaks": cadence_breaks,
            "longest_samples": longest,
            "reasons": reasons,
            "requires_original": requires_original,
        },
    }
