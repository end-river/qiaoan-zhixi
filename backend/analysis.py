"""Deterministic statistical tools; labels never enter fitting or prediction."""

import io
import numpy as np
import pandas as pd

FREQ = ["f1", "f2", "f3", "f4"]
REQUIRED = ["date", "temperature", *FREQ]


def validate_csv(content: bytes):
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("CSV 最大为 10 MB")
    try:
        df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    except Exception as exc:
        raise ValueError("无法读取 CSV，请使用 UTF-8 编码、逗号分隔") from exc
    missing = [c for c in REQUIRED if c not in df]
    if missing:
        raise ValueError("缺少列：" + ", ".join(missing))
    if not 30 <= len(df) <= 20000:
        raise ValueError("样本数量须在 30 到 20000 之间")
    dates = pd.to_datetime(df.date, errors="coerce", format="%Y-%m-%d")
    if dates.isna().any():
        raise ValueError("date 含缺失或无效日期，格式应为 YYYY-MM-DD")
    if dates.duplicated().any():
        raise ValueError("存在重复日期，请先核查原始数据")
    df["date"] = dates.dt.strftime("%Y-%m-%d")
    for col in REQUIRED[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = ~np.isfinite(df[col])
        if bad.any():
            rows = (np.flatnonzero(bad)[:5] + 2).tolist()
            raise ValueError(f"{col} 含缺失、非数值或无限值，CSV 行号：{rows}")
    if (df[FREQ] <= 0).any().any():
        raise ValueError("模态频率必须大于零，单位 Hz")
    if "damage" in df:
        df["damage"] = pd.to_numeric(df.damage, errors="coerce")
        if not df.damage.isin([0, 1]).all():
            raise ValueError("可选 damage 标签必须为 0 或 1")
    df = df.sort_values("date").reset_index(drop=True)
    return df[REQUIRED + (["damage"] if "damage" in df else [])]


def demo_frames():
    for name, title in [
        ("normal", "季节温变 · 正常基线"),
        ("drift", "渐进漂移 · 多模态变化"),
        ("sensor", "传感器异常 · 瞬时尖峰"),
    ]:
        rng = np.random.default_rng(20261115)
        n = 365
        t = 15 + 18 * np.sin(np.arange(n) * 2 * np.pi / n) + rng.normal(0, 1.8, n)
        x = (
            np.array([3.9, 4.95, 9.8, 10.85])
            + (t[:, None] - 15) * np.array([-0.0025, -0.0028, -0.0035, -0.004])
            + rng.normal(0, 0.004, (n, 4))
        )
        label = np.zeros(n, dtype=int)
        if name == "drift":
            x[290:] -= np.linspace(0.001, 0.065, n - 290)[:, None] * np.array(
                [1, 0.8, 1.4, 1.1]
            )
            label[290:] = 1
        if name == "sensor":
            for day in [240, 267, 302, 335, 350]:
                x[day, 0] += 0.09
                label[day] = 1
        df = pd.DataFrame(x, columns=FREQ).round(5)
        df.insert(0, "temperature", t.round(3))
        df.insert(
            0, "date", pd.date_range("2025-01-01", periods=n).strftime("%Y-%m-%d")
        )
        df["damage"] = label
        yield name, title, df


def analyze(records, start, end):
    df = pd.DataFrame(records)
    reference = (df.date >= start) & (df.date <= end)
    if start > end or reference.sum() < 30:
        raise ValueError("健康参考区间须包含至少 30 个样本，且开始日期不晚于结束日期")
    t = df.temperature.to_numpy(float)
    if np.ptp(t[reference]) < 1:
        raise ValueError("参考区间温差不足 1°C，无法稳定拟合温度效应")
    x = df[FREQ].to_numpy(float)
    design = np.column_stack([np.ones(len(t)), t])
    coefficients = np.linalg.lstsq(design[reference], x[reference], rcond=None)[0]
    predicted = design @ coefficients
    residual = x - predicted
    ref = residual[reference]
    std = np.maximum(ref.std(axis=0, ddof=1), 1e-8)
    z = (residual - ref.mean(axis=0)) / std
    cov = np.cov(ref.T)
    regularizer = max(float(np.trace(cov)) / 4 * 1e-6, 1e-10)
    inverse = np.linalg.pinv(cov + np.eye(4) * regularizer)
    centered = residual - ref.mean(axis=0)
    d2 = np.einsum("ij,jk,ik->i", centered, inverse, centered)
    threshold = max(float(np.quantile(d2[reference], 0.999)), 1e-8)
    flags = d2 > threshold
    # Baseline points are not operational alerts; expose in-sample exceedances separately.
    evaluation = df.date.to_numpy() > end
    operational = flags & evaluation
    onset = None
    for i in range(2, len(df)):
        if operational[i - 2 : i + 1].all():
            onset = df.date.iloc[i - 2]
            break
    metrics = None
    if "damage" in df:
        truth = df.damage.to_numpy() == 1
        tp = int((truth & flags & evaluation).sum())
        fp = int((~truth & flags & evaluation).sum())
        fn = int((truth & ~flags & evaluation).sum())
        tn = int((~truth & ~flags & evaluation).sum())
        first_true = np.flatnonzero(truth & evaluation)
        first_hit = np.flatnonzero(truth & operational)
        delay = None
        if len(first_hit) and len(first_true):
            delay = int(
                (
                    pd.Timestamp(df.date.iloc[first_hit[0]])
                    - pd.Timestamp(df.date.iloc[first_true[0]])
                ).days
            )
        metrics = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "miss_rate": fn / (tp + fn) if tp + fn else None,
            "detection_delay_days": delay,
        }
    corr = np.nan_to_num(np.corrcoef(residual.T), nan=0).round(3).tolist()
    return {
        "reference": {"start": start, "end": end, "count": int(reference.sum())},
        "summary": {
            "samples": len(df),
            "evaluated": int(evaluation.sum()),
            "anomalies": int(operational.sum()),
            "onset": onset,
            "threshold": threshold,
            "max_score": float(d2.max()),
            "baseline_exceedances": int((flags & reference).sum()),
        },
        "dates": df.date.tolist(),
        "temperature": t.tolist(),
        "frequency": x.round(6).tolist(),
        "predicted": predicted.round(6).tolist(),
        "residual": residual.round(6).tolist(),
        "z": z.round(4).tolist(),
        "score": d2.round(5).tolist(),
        "flags": operational.astype(int).tolist(),
        "mode_flags": (np.abs(z) > 3).astype(int).tolist(),
        "models": [
            {
                "mode": c,
                "intercept": float(coefficients[0, i]),
                "slope": float(coefficients[1, i]),
                "reference_std": float(std[i]),
            }
            for i, c in enumerate(FREQ)
        ],
        "correlation": corr,
        "metrics": metrics,
        "limitations": [
            "健康参考区间由用户指定，若包含异常会污染基准。",
            "阈值为参考样本的经验分位，未保证真实场景的误报率。",
            "统计异常不等同于结构损伤，需结合传感器核查及专业复检。",
        ],
    }
