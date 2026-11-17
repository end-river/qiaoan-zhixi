"""Bounded numerical operations shared by the HTTP interface and AI tools."""

import math
from collections import Counter

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from scipy import signal
from statsmodels.tsa.seasonal import STL

from . import monitor_data as data
from .monitor_forecast import forecast

METHODS = {
    "quality": "数据质量检查",
    "trend": "趋势与描述统计",
    "compare": "时段对比",
    "change": "变化量与变化速率",
    "rolling": "滚动统计",
    "correlation": "测点关联",
    "lag": "互相关时滞",
    "clean": "数据清洗",
    "resample": "重采样",
    "moving": "移动平均",
    "savgol": "Savitzky–Golay 平滑",
    "detrend": "线性去趋势",
    "filter": "Butterworth 低通滤波",
    "fft": "FFT 幅度谱",
    "welch": "Welch 功率谱",
    "stl": "STL 趋势与周期分解",
    "anomaly": "异常事件识别",
    "forecast": "短期趋势预测",
    "limits": "历史超限检查",
}
SIGNAL_TRANSFORMS = {"moving", "savgol", "detrend", "filter"}
CONTINUOUS_METHODS = SIGNAL_TRANSFORMS | {"fft", "welch", "stl", "lag", "forecast"}


class ObservationIntervalError(ValueError):
    """The method can be retried with a different continuous observation window."""


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    channel: str
    unit: str = Field(max_length=30)
    lower: float | None = Field(None, ge=-1e100, le=1e100)
    upper: float | None = Field(None, ge=-1e100, le=1e100)
    rate: float | None = Field(None, gt=0, le=1e100)
    duration: float = Field(0, ge=0, le=1e10)
    source: str = Field(min_length=1, max_length=200)


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    channels: list[str] = Field(default_factory=list, max_length=32)
    start: str | None = None
    end: str | None = None
    start_b: str | None = None
    end_b: str | None = None
    window: int = Field(12, ge=3, le=1001)
    interval_seconds: float | None = Field(None, ge=0.001, le=10_000_000)
    period_seconds: float | None = Field(None, ge=0.002, le=100_000_000)
    cutoff_hz: float | None = Field(None, gt=0, le=500)
    duplicate: str = "keep"
    outliers: str = "keep"
    fill_seconds: float = Field(0, ge=0, le=10_000_000)
    coefficient: str = "pearson"
    max_lag: int = Field(24, ge=1, le=250)
    threshold: float = Field(4, gt=0, le=50)
    steps: int | None = Field(None, ge=1, le=24)
    rule: Rule | None = None


def minimum_samples(method, params):
    if method == "filter":
        return 16
    if method == "forecast":
        return max(60, 30 + 3 * (params.steps or 1))
    if method in ("moving", "savgol"):
        return max(8, params.window)
    return 8


def observation_bounds(method, params, interval):
    """Shared bounds for an already continuous window at the given cadence."""
    minimum = minimum_samples(method, params)
    maximum = None
    period = None
    if method == "savgol" and params.window % 2 == 0:
        raise ValueError("Savitzky–Golay 窗口须为奇数")
    if method == "filter" and params.cutoff_hz is not None and params.cutoff_hz >= 0.5 / interval:
        raise ObservationIntervalError(
            f"该采样间隔下，截止频率须小于 {0.5 / interval:g} Hz"
        )
    if method == "stl" and params.period_seconds is not None:
        ratio = params.period_seconds / interval
        period = round(ratio)
        if period < 2 or not math.isclose(ratio, period, abs_tol=1e-6, rel_tol=0):
            raise ObservationIntervalError("周期须为至少两个采样间隔的整数倍")
        if period > 2000:
            raise ObservationIntervalError("STL 周期采样点过多，请先重采样")
        minimum = max(minimum, 2 * period)
        maximum = 20_000_000 // period
    return minimum, maximum, period


def require_series(series, minimum=8):
    interval, regular = data.interval_info(series.index)
    if len(series) < minimum:
        raise ObservationIntervalError(f"该方法至少需要 {minimum} 个有效样本")
    if not regular or series.isna().any():
        raise ObservationIntervalError(
            "该方法需要等间隔且无缺测的数据。请选取连续区段，或先确认重采样及缺口处理。"
        )
    return interval


def require_observations(series, method, params):
    interval = require_series(series, minimum_samples(method, params))
    if method == "filter" and params.cutoff_hz is None:
        raise ValueError("请设置 Butterworth 截止频率")
    if method == "stl" and params.period_seconds is None:
        raise ValueError("请指定周期时长，例如 1440 分钟表示一天")
    minimum, maximum, period = observation_bounds(method, params, interval)
    if len(series) < minimum:
        raise ObservationIntervalError(f"区间须覆盖至少两个完整周期（{minimum} 个样本）")
    if maximum is not None and len(series) > maximum:
        raise ObservationIntervalError("STL 周期与样本规模过大，请缩短区段")
    return interval, period


def date_limit(value, end=False):
    if value is None:
        return None
    parsed = data.parse_time(value)
    if parsed is None:
        raise ValueError("时间格式无效，请使用年-月-日和可选时分秒")
    stamp = pd.Timestamp(parsed)
    return (
        stamp + pd.Timedelta(days=1, milliseconds=-1)
        if end and len(value.strip()) == 10
        else stamp
    )


def time_slice(frame, start, end, *, allow_empty=False):
    lo, hi = date_limit(start), date_limit(end, True)
    if lo is not None and hi is not None and lo > hi:
        raise ValueError("开始时间不能晚于结束时间")
    if lo is not None:
        frame = frame[frame.index >= lo]
    if hi is not None:
        frame = frame[frame.index <= hi]
    if frame.empty and not allow_empty:
        raise ValueError("所选时间范围内没有数据")
    return frame


def series_payload(series, name, unit, *, group=None, kind="time", style="line"):
    axis = (
        [data.time_string(t) for t in series.index]
        if kind == "time"
        else [float(t) for t in series.index]
    )
    return {
        "name": name,
        "unit": unit,
        "group": group or unit,
        "kind": kind,
        "style": style,
        "points": [
            [x, float(y) if np.isfinite(y) else None] for x, y in zip(axis, series)
        ],
    }


def roll_flags(series, p):
    history = series.shift()
    rolling = history.rolling(p.window, min_periods=p.window)
    base = rolling.median()
    mad = rolling.apply(lambda a: np.median(np.abs(a - np.median(a))), raw=True)
    scale = (1.4826 * mad).clip(lower=max(float(series.abs().max() or 0) * 1e-9, 1e-9))
    deviation = (series - base).abs()
    spike = deviation > p.threshold * scale
    recent = series.rolling(3, min_periods=3)
    prior = series.shift(3).rolling(p.window, min_periods=p.window)
    delta = recent.median() - prior.median()
    prior_mad = prior.apply(lambda a: np.median(np.abs(a - np.median(a))), raw=True)
    prior_scale = (1.4826 * prior_mad).clip(lower=1e-9)
    sustained = (delta.abs() > max(2, p.threshold * 0.75) * prior_scale) & (
        ((series - prior.median()) * np.sign(delta)) > 2 * prior_scale
    )
    variation = (
        recent.std() > p.threshold * prior.std().clip(lower=1e-9)
    ) & series.notna()
    return (
        {
            "尖峰偏离": spike.fillna(False),
            "持续偏移": sustained.fillna(False),
            "波动增大": variation.fillna(False),
        },
        base - p.threshold * scale,
        base + p.threshold * scale,
    )


def events_for(series, flags, channel, max_gap, minimum=0):
    events = []
    active = None

    def flush():
        if active is None:
            return
        seconds = (active["end"] - active["start"]).total_seconds()
        if seconds >= minimum:
            events.append(
                {
                    "测点": channel,
                    "开始": data.time_string(active["start"]),
                    "结束": data.time_string(active["end"]),
                    "持续秒数": seconds,
                    "样本数": active["count"],
                    "最小值": active["min"],
                    "最大值": active["max"],
                    "触发依据": "、".join(sorted(active["reasons"])),
                }
            )

    for stamp, value, row in zip(
        series.index, series, zip(*(mask.to_numpy() for mask in flags.values()))
    ):
        reasons = {name for name, hit in zip(flags, row) if hit}
        if active is not None and (
            not reasons or (stamp - active["end"]).total_seconds() > max_gap
        ):
            flush()
            active = None
        if not reasons or not np.isfinite(value):
            continue
        if active is None:
            active = {
                "start": stamp,
                "end": stamp,
                "count": 0,
                "min": float(value),
                "max": float(value),
                "reasons": set(),
            }
        active["end"] = stamp
        active["count"] += 1
        active["reasons"].update(reasons)
        active["min"] = min(active["min"], value)
        active["max"] = max(active["max"], value)
    flush()
    return events


def validate_rule(rule, dataset):
    channel = next((c for c in dataset["channels"] if c["name"] == rule.channel), None)
    if channel is None or channel["unit"] != rule.unit:
        raise ValueError("超限规则的测点和单位必须匹配当前数据")
    if rule.lower is None and rule.upper is None and rule.rate is None:
        raise ValueError("请填写上限、下限或变化速率限值")
    if rule.lower is not None and rule.upper is not None and rule.lower >= rule.upper:
        raise ValueError("下限必须小于上限")
    if not rule.source.strip():
        raise ValueError("请填写阈值来源")


def limited_interpolation(frame, selected, seconds):
    for column in selected:
        s = frame[column]
        valid = s.index[s.notna()]
        positions = valid.searchsorted(s.index)
        keep = (positions > 0) & (positions < len(valid))
        allowed = np.zeros(len(s), dtype=bool)
        if len(valid) >= 2:
            p = positions[keep]
            allowed[keep] = (valid[p].asi8 - valid[p - 1].asi8) <= seconds * 1e9
        filled = s.interpolate(method="time", limit_area="inside")
        frame[column] = s.where(~(s.isna() & allowed), filled)


def quality(frame, version, selected):
    times = frame.index
    interval, regular = data.interval_info(times)
    duplicate = times.duplicated(keep=False)
    bins = np.linspace(0, len(times), min(24, len(times)) + 1, dtype=int)
    stamps = [data.time_string(times[i]) for i in bins[:-1]]
    heatmap = []
    start, end = data.time_string(times[0]), data.time_string(times[-1])
    issues = [
        issue
        for issue in version["issues"]
        if issue["time"] is None
        or (start <= issue["time"] <= end and issue["channel"] in selected)
    ]
    issue_totals = Counter((issue["channel"], issue["kind"]) for issue in issues)
    original = version["parent_id"] is None
    if original:
        duplicates = set_duplicates(times, duplicate)
        for r in version["records"]:
            if r[0] in duplicates:
                issues.append(
                    {
                        "row": r[1],
                        "time": r[0],
                        "kind": "重复时间",
                        "channel": "时间",
                        "value": "",
                    }
                )
    rows = []
    for j, c in enumerate(selected):
        s = frame[c]
        missing = s.isna()
        gaps = times.to_series().diff().dt.total_seconds()
        gap_flags = (
            (gaps > interval) if interval is not None else pd.Series(False, index=times)
        )
        same = s.notna() & s.eq(s.shift())
        run = same.groupby((~same).cumsum()).cumsum() >= 4
        for i, (a, b) in enumerate(zip(bins[:-1], bins[1:])):
            flag = (
                missing.to_numpy()[a:b]
                | duplicate[a:b]
                | run.to_numpy()[a:b]
                | gap_flags.to_numpy()[a:b]
            )
            heatmap.append([i, j, int(flag.sum())])
        rows.append(
            {
                "测点": c,
                "总行数": len(s),
                "有效值": int(s.count()),
                "缺失或无效": int(missing.sum()),
                "原始非数值": issue_totals[c, "非数值"],
                "重复时间行": int(duplicate.sum()),
                "采样间断": int(gap_flags.sum()),
                "连续持平标记": int(run.sum()),
                "常见间隔秒": interval,
                "等间隔": "是" if regular else "否",
            }
        )
    return rows, issues, {"bins": stamps, "channels": selected, "cells": heatmap}


def set_duplicates(times, duplicate):
    return {data.time_string(t) for t in times[duplicate]}


def duration_text(seconds):
    for divisor, label in ((86400, "天"), (3600, "小时"), (60, "分钟")):
        if seconds >= divisor and seconds % divisor == 0:
            return f"{seconds / divisor:g} {label}"
    return f"{seconds:g} 秒"


def calculate(dataset, version, method, p, check=lambda: None):
    if method not in METHODS:
        raise ValueError("未知分析工具")
    original = data.frame(dataset, version)
    selected = p.channels or [c["name"] for c in dataset["channels"]]
    if len(set(selected)) != len(selected) or any(c not in original for c in selected):
        raise ValueError("选择的测点不存在或重复")
    units = {c["name"]: c["unit"] or "未注明" for c in dataset["channels"]}
    if method == "limits":
        if p.rule is None:
            raise ValueError("请设置并确认超限规则")
        validate_rule(p.rule, dataset)
        selected = [p.rule.channel]
    full = time_slice(original, p.start, p.end, allow_empty=method in CONTINUOUS_METHODS)
    if full.empty:
        raise ObservationIntervalError("所选时间范围内没有观测数据")
    values = full[selected]
    result = {
        "method": method,
        "title": METHODS[method],
        "dataset_id": dataset["id"],
        "version_id": version["id"],
        "created_version_id": None,
        "parameters": p.model_dump(exclude_none=True) | {"channels": selected},
        "range": [
            data.time_string(values.index[0]),
            data.time_string(values.index[-1]),
        ],
        "summary": "",
        "series": [],
        "rows": [],
        "events": [],
        "issues": [],
        "limits": [],
        "notes": [],
        "steps": version["steps"],
        "heatmap": None,
        "backtest": [],
        "forecast": [],
    }
    series, rows, events = result["series"], result["rows"], result["events"]
    interval, _ = data.interval_info(values.index)

    def add(s, c, label=None, **kwargs):
        series.append(series_payload(s, label or c, units[c], **kwargs))

    if method == "quality":
        quality_rows, result["issues"], heatmap = quality(values, version, selected)
        rows.extend(quality_rows)
        result["heatmap"] = heatmap
        result["summary"] = (
            f"检查了 {len(values):,} 行、{len(selected)} 个测点。原表问题明细 {len(result['issues']):,} 条。"
        )
        result["notes"].append(
            "热力图每格表示该时间分箱内有缺失、重复、采样间断或持续持平标记的行数。"
        )
    elif method in ("trend", "compare"):
        if method == "compare" and (not p.start_b or not p.end_b):
            raise ValueError("请选择对比时段的起止时间")
        periods = [("A 时段", values)]
        if method == "compare":
            periods.append(
                ("B 时段", time_slice(original, p.start_b, p.end_b)[selected])
            )
        for label, subset in periods:
            for c in selected:
                s = subset[c]
                add(s, c, f"{c} · {label}" if method == "compare" else c)
                valid = s.dropna()
                rows.append(
                    {
                        "测点": c,
                        "时段": label,
                        "单位": units[c],
                        "有效值": len(valid),
                        "均值": valid.mean() if len(valid) else None,
                        "标准差": valid.std(ddof=0) if len(valid) else None,
                        "最小值": valid.min() if len(valid) else None,
                        "最大值": valid.max() if len(valid) else None,
                        "首末变化": float(valid.iloc[-1] - valid.iloc[0])
                        if len(valid)
                        else None,
                    }
                )
        result["summary"] = (
            f"已汇总 {len(selected)} 个测点的{'两个时间段' if method == 'compare' else '观测趋势'}。"
        )
    elif method in ("clean", "resample"):
        changed = full.copy()
        if p.duplicate not in ("keep", "first", "mean") or p.outliers not in (
            "keep",
            "mark",
            "exclude",
        ):
            raise ValueError("未知清洗选项")
        if p.duplicate == "first":
            changed = changed[~changed.index.duplicated(keep="first")]
        elif p.duplicate == "mean":
            changed = changed.groupby(level=0).mean()
        if method == "resample":
            if p.interval_seconds is None:
                raise ValueError("请指定重采样间隔（秒）")
            millis = p.interval_seconds * 1000
            if not math.isclose(millis, round(millis), rel_tol=0, abs_tol=1e-6):
                raise ValueError("重采样间隔需要是整数毫秒")
            if (
                changed.index[-1] - changed.index[0]
            ).total_seconds() / p.interval_seconds >= data.MAX_ROWS:
                raise ValueError("处理结果超过 100,000 行，请增大采样间隔")
            changed = changed.resample(f"{round(millis)}ms", origin="start").mean()
        masks = {}
        if p.outliers != "keep":
            for c in selected:
                flags, _, _ = roll_flags(changed[c], p)
                mask = np.logical_or.reduce([x.to_numpy() for x in flags.values()])
                masks[c] = int(mask.sum())
                if p.outliers == "exclude":
                    changed.loc[mask, c] = np.nan
                if p.outliers == "mark":
                    events.extend(
                        events_for(changed[c], flags, c, (interval or 0.001) * 1.5)
                    )
        if p.fill_seconds:
            if changed.index.has_duplicates:
                raise ValueError("插值前请先选择重复时间处理方式")
            limited_interpolation(changed, selected, p.fill_seconds)
        for c in selected:
            add(full[c], c, f"{c} · 原始输入", style="reference")
            add(changed[c], c, f"{c} · 处理后")
            rows.append(
                {
                    "测点": c,
                    "处理前有效": int(full[c].count()),
                    "处理后有效": int(changed[c].count()),
                    "异常标记": masks.get(c, 0),
                    "处理后空值": int(changed[c].isna().sum()),
                }
            )
        result["_derived"] = (changed, None)
        result["summary"] = f"处理前 {len(full):,} 行，处理后 {len(changed):,} 行。"
        result["notes"].append(
            "原始文件不变。插值只填补两端有观测、间隔不超过设定值的空值，不进行外推。"
        )
    elif method in ("correlation", "lag"):
        if len(selected) < 2 or (method == "lag" and len(selected) != 2):
            raise ValueError("关联分析至少选择两个测点，时滞分析请选择两个测点")
        if values.index.has_duplicates:
            raise ValueError("请先处理重复时间，再进行测点关联")
        if p.coefficient not in ("pearson", "spearman"):
            raise ValueError("选择 Pearson 或 Spearman 关联")
        if method == "correlation":
            corr = values.corr(method=p.coefficient, min_periods=3)
            result["heatmap"] = {
                "bins": selected,
                "channels": selected,
                "cells": [
                    [i, j, float(corr.iloc[j, i])]
                    for i in range(len(selected))
                    for j in range(len(selected))
                    if pd.notna(corr.iloc[j, i])
                ],
                "correlation": True,
            }
            for i, a in enumerate(selected):
                for b in selected[i + 1 :]:
                    rows.append(
                        {
                            "测点 A": a,
                            "测点 B": b,
                            "相关系数": corr.at[a, b]
                            if pd.notna(corr.at[a, b])
                            else None,
                            "共同有效样本": int(
                                (values[a].notna() & values[b].notna()).sum()
                            ),
                        }
                    )
        else:
            a, b = (values[c] for c in selected)
            dt, _ = require_observations(a, method, p)
            require_series(b)
            if a.nunique() < 2 or b.nunique() < 2:
                raise ObservationIntervalError("常数序列无法计算时滞相关")
            for lag in range(
                -min(p.max_lag, len(a) - 3), min(p.max_lag, len(a) - 3) + 1
            ):
                score = a.corr(b.shift(-lag))
                if pd.notna(score):
                    rows.append(
                        {"时滞秒": round(lag * dt, 6), "相关系数": float(score)}
                    )
            result["series"].append(
                series_payload(
                    pd.Series({r["时滞秒"]: r["相关系数"] for r in rows}),
                    "互相关",
                    "相关系数",
                    kind="lag",
                )
            )
            result["notes"].append("正时滞表示第二个测点滞后于第一个测点。")
        result["summary"] = "已按共同时间计算测点关系，系数仅表示统计关联。"
    else:
        transformed = full.copy() if method in SIGNAL_TRANSFORMS else None
        for c in selected:
            check()
            s = values[c]
            if method == "change":
                elapsed = s.index.to_series().diff().dt.total_seconds()
                add(s.diff(), c, f"{c} · 变化量")
                series.append(
                    series_payload(
                        s.diff().div(elapsed.where(elapsed > 0)),
                        f"{c} · 变化速率",
                        units[c] + "/s",
                    )
                )
            elif method == "rolling":
                roll = s.rolling(p.window, min_periods=p.window)
                add(s, c)
                add(roll.mean(), c, f"{c} · 滚动均值")
                add(roll.std(), c, f"{c} · 滚动标准差", group=f"{c} · 波动")
            elif method == "anomaly":
                if int(s.count()) <= p.window:
                    raise ValueError("有效样本数须大于异常检测窗口")
                flags, lo, hi = roll_flags(s, p)
                events.extend(events_for(s, flags, c, (interval or 0.001) * 1.5))
                add(s, c)
                add(lo, c, f"{c} · 统计下界", style="reference")
                add(hi, c, f"{c} · 统计上界", style="reference")
            elif method == "limits":
                if s.index.has_duplicates:
                    raise ValueError("请先处理重复时间，再检查超限事件")
                rule = p.rule
                elapsed = s.index.to_series().diff().dt.total_seconds()
                flags = {}
                if rule.upper is not None:
                    flags["高于上限"] = s > rule.upper
                    result["limits"].append(
                        {"name": "上限", "value": rule.upper, "unit": units[c]}
                    )
                if rule.lower is not None:
                    flags["低于下限"] = s < rule.lower
                    result["limits"].append(
                        {"name": "下限", "value": rule.lower, "unit": units[c]}
                    )
                if rule.rate is not None:
                    rate = (
                        s.diff()
                        .abs()
                        .div(
                            elapsed.where(
                                (elapsed > 0) & (elapsed <= (interval or 0.001) * 1.5)
                            )
                        )
                    )
                    flags["绝对变化速率超限"] = rate > rule.rate
                events.extend(
                    events_for(s, flags, c, (interval or 0.001) * 1.5, rule.duration)
                )
                add(s, c)
            elif method == "forecast":
                if len(selected) != 1:
                    raise ValueError("请选择一个测点进行预测")
                if version["parent_id"]:
                    raise ObservationIntervalError(
                        "请切换至原始版本，选取连续无缺测区段进行预测，以隔离历史回测"
                    )
                dt, _ = require_observations(s, method, p)
                best, metrics, backtest, future = forecast(s, dt, p.steps, check)
                add(s, c)
                for key, style in (
                    ("预测", "forecast"),
                    ("下界", "lower"),
                    ("上界", "upper"),
                ):
                    add(
                        pd.Series({pd.Timestamp(r["时间"]): r[key] for r in future}),
                        c,
                        f"{c} · {key}",
                        style=style,
                    )
                rows.extend(metrics)
                result["backtest"] = backtest
                result["forecast"] = future
                result["parameters"]["steps"] = len(future)
                horizon = duration_text(len(future) * dt)
                result["summary"] = (
                    f"{c} 预测 {len(future)} 步（{horizon}），采用 {best['模型']}。历史回测 MAE 为 {best['MAE']:.4g} {units[c]}。"
                )
                result["notes"].append(
                    "三段按时间顺序回测。阴影为 95% 模型预测区间，实际覆盖率取决于数据与模型。"
                )
                if p.rule:
                    validate_rule(p.rule, dataset)
                    if p.rule.channel != c:
                        raise ValueError("超限规则须匹配预测测点")
                    result["notes"].append(
                        "预测提示评估数值上下限；持续时长和变化速率规则适用于历史超限检查。"
                    )
                    for name, bound, sign in (
                        ("上限", p.rule.upper, 1),
                        ("下限", p.rule.lower, -1),
                    ):
                        if bound is None:
                            continue
                        result["limits"].append(
                            {"name": name, "value": bound, "unit": units[c]}
                        )
                        for row in future:
                            outer = row["上界"] if sign == 1 else row["下界"]
                            if sign * (outer - bound) >= 0:
                                events.append(
                                    {
                                        "测点": c,
                                        "开始": row["时间"],
                                        "结束": row["时间"],
                                        "触发依据": f"预测中值越过{name}"
                                        if sign * (row["预测"] - bound) > 0
                                        else f"预测区间触及{name}",
                                        "预测值": row["预测"],
                                    }
                                )
            else:
                dt, period = require_observations(s, method, p)
                x = s.to_numpy()
                if transformed is not None:
                    add(s, c, f"{c} · 输入信号", style="reference")
                    if method == "moving":
                        filtered = (
                            s.rolling(p.window, min_periods=p.window).mean().to_numpy()
                        )
                    elif method == "savgol":
                        filtered = signal.savgol_filter(x, p.window, 2)
                    elif method == "filter":
                        filtered = signal.sosfiltfilt(
                            signal.butter(4, p.cutoff_hz, fs=1 / dt, output="sos"), x
                        )
                    else:
                        filtered = signal.detrend(x)
                    add(pd.Series(filtered, index=s.index), c, f"{c} · 处理结果")
                    transformed[c] = filtered
                elif method == "stl":
                    split = STL(x, period=period, robust=True).fit()
                    for label, y in (
                        ("实测", x),
                        ("趋势", split.trend),
                        ("周期", split.seasonal),
                        ("剩余", split.resid),
                    ):
                        add(
                            pd.Series(y, index=s.index),
                            c,
                            f"{c} · {label}",
                            group=f"{c} · {label}",
                        )
                    rows.append(
                        {"测点": c, "周期秒": p.period_seconds, "周期采样点": period}
                    )
                else:
                    if method == "fft":
                        f = np.fft.rfftfreq(len(x), dt)
                        y = np.abs(np.fft.rfft(x - x.mean())) / len(x)
                        y[1 : (-1 if len(x) % 2 == 0 else None)] *= 2
                        unit = units[c]
                    else:
                        f, y = signal.welch(x, fs=1 / dt, nperseg=min(256, len(x)))
                        unit = units[c] + "²/Hz"
                    series.append(
                        series_payload(pd.Series(y, index=f), c, unit, kind="frequency")
                    )
                    peak = int(np.argmax(y[1:]) + 1)
                    if y[peak] > 0:
                        rows.append(
                            {
                                "测点": c,
                                "主要频率 Hz": float(f[peak]),
                                "对应周期秒": float(1 / f[peak]),
                                "峰值": float(y[peak]),
                            }
                        )
        if method in ("anomaly", "limits"):
            result["summary"] = (
                f"{len(selected)} 个测点共发现 {len(events)} 个{'统计异常' if method == 'anomaly' else '历史超限'}事件。"
            )
            result["notes"].append(
                "事件按相邻观测合并，缺测或采样中断会结束事件。事件表示当前数据命中规则。"
            )
        elif method in ("fft", "welch"):
            result["notes"].append("频峰代表信号中的频率成分。")
        if transformed is not None:
            result["_derived"] = (transformed, None)
    if "_derived" in result and (p.start or p.end):
        result["notes"].append(
            "处理版本仅包含本次所选时间范围；可切回输入版本查看全部记录。"
        )
    check()
    if not result["summary"]:
        result["summary"] = f"已完成 {len(selected)} 个测点的{METHODS[method]}。"
    return result
