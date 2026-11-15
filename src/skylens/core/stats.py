"""集合统计 —— 从旧仓 ``tools/statistics.py`` 迁移（算法保留，签名净化）。

三处必改（见 ``docs/MIGRATION.md`` §2.1）：

1. 输入从「分模式数组」改为「ensemble 成员数组」（每个成员一条记录）；
2. 删掉 ``_is_daily_data`` 靠猜字段名的逻辑，改为显式 ``kind="daily"|"hourly"``；
3. 输出直接对齐 fact_pack 契约：``{"mean", "p10", "p90", "spread"}``，离散度 = p90 - p10。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

import numpy as np

from skylens.core import vocab

Kind = Literal["daily", "hourly"]

# fact_pack 字段 → (daily/hourly 里的变量名, 分级用的要素类)
AGREEMENT_FIELDS: dict[str, tuple[str, str]] = {
    "temperature_max": ("temp_max", "temperature"),
    "temperature_min": ("temp_min", "temperature"),
    "precipitation": ("precip_mm", "precipitation"),
    "wind": ("wind_max_ms", "wind"),
}


def extract_variable_data(
    record: Mapping[str, Any], variable: str, *, kind: Kind = "daily"
) -> np.ndarray:
    """从一个 ensemble 成员记录里取出某个变量的时间序列（NaN 已剔除）。

    ``record`` 形如 ``{"model": "ecmwf_ifs025", "daily": {"temp_max": [...]}, "hourly": {...}}``。
    """
    if kind not in ("daily", "hourly"):
        raise ValueError(f"kind 只能是 daily 或 hourly，收到 {kind!r}")
    container = record.get(kind)
    if not isinstance(container, Mapping):
        raise ValueError(f"成员记录缺少 {kind!r} 块")
    raw = container.get(variable)
    if raw is None:
        raise ValueError(f"{kind!r} 块缺少变量 {variable!r}")
    values = np.asarray(raw, dtype=float).ravel()
    return values[~np.isnan(values)]


def _aggregate(values: np.ndarray, *, use_max: bool) -> float:
    if values.size == 0:
        return float("nan")
    return float(values.max() if use_max else values.min())


def summarize_values(
    values: Sequence[float], *, percentiles: tuple[float, float] = (10.0, 90.0)
) -> dict[str, float]:
    """一组值的集合统计：均值 + p10/p90 + 离散度（= p90 - p10）。

    这是 fact_pack 里 ``{"mean","p10","p90","spread"}`` 的唯一实现；
    ensemble 成员先各自压成一个值，再喂进来。
    """
    low_p, high_p = percentiles
    array = np.asarray(list(values), dtype=float)
    array = array[~np.isnan(array)]
    if array.size == 0:
        return {
            "mean": float("nan"),
            "p10": float("nan"),
            "p90": float("nan"),
            "spread": float("nan"),
        }
    p10, p90 = (float(v) for v in np.percentile(array, [low_p, high_p]))
    return {
        "mean": round(float(array.mean()), 2),
        "p10": round(p10, 2),
        "p90": round(p90, 2),
        "spread": round(p90 - p10, 2),
    }


def calculate_ensemble_statistics(
    members: Sequence[Mapping[str, Any]],
    variable: str,
    *,
    kind: Kind = "daily",
    use_max: bool = False,
    percentiles: tuple[float, float] = (10.0, 90.0),
) -> dict[str, float]:
    """ensemble 成员的集合统计：均值 + p10/p90 + 离散度。

    每个成员先按 ``use_max`` 沿时间轴压成一个值（最高温取 max、最低温取 min），
    再在成员之间做统计——这正是「多模式一致吗」要回答的量。
    """
    per_member = [
        _aggregate(extract_variable_data(m, variable, kind=kind), use_max=use_max) for m in members
    ]
    return summarize_values(per_member, percentiles=percentiles)


def calculate_model_agreement(
    values: float | Sequence[float], variable: str = "temperature"
) -> dict[str, str | float]:
    """一致性等级。可直接喂一个离散度，也可喂一组成员值（自动算 p90-p10）。"""
    if isinstance(values, (int, float)):
        spread = float(values)
    else:
        array = np.asarray(list(values), dtype=float)
        array = array[~np.isnan(array)]
        spread = (
            0.0 if array.size == 0 else float(np.percentile(array, 90) - np.percentile(array, 10))
        )
    return vocab.agreement(variable, spread)


def summarize_forecast_uncertainty(
    daily: Sequence[Mapping[str, Any]], *, basis: str = ""
) -> dict[str, dict[str, str | float]]:
    """把逐日统计汇总成 fact_pack 的 ``forecast.agreement``。

    多天时取各天里最差的离散度（最保守），不让一天的乐观掩盖另一天的分歧。
    """
    summary: dict[str, dict[str, str | float]] = {}
    for field, (key, variable) in AGREEMENT_FIELDS.items():
        spreads: list[float] = []
        for day in daily:
            block = day.get(key)
            if isinstance(block, Mapping) and block.get("spread") is not None:
                spreads.append(float(block["spread"]))
        if not spreads:
            continue
        summary[field] = calculate_model_agreement(max(spreads), variable)
        if basis:
            summary[field]["basis"] = basis
    return summary


def calculate_daily_temperature_range_statistics(
    daily: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """日较差（最高 - 最低）的集合统计，用于「昼夜温差大」这类事实陈述。"""
    ranges: list[float] = []
    for day in daily:
        high = day.get("temp_max")
        low = day.get("temp_min")
        if not isinstance(high, Mapping) or not isinstance(low, Mapping):
            continue
        high_mean, low_mean = high.get("mean"), low.get("mean")
        if high_mean is None or low_mean is None:
            continue
        ranges.append(float(high_mean) - float(low_mean))
    if not ranges:
        return {"mean": float("nan"), "min": float("nan"), "max": float("nan"), "n": 0}
    array = np.asarray(ranges, dtype=float)
    return {
        "mean": round(float(array.mean()), 2),
        "min": round(float(array.min()), 2),
        "max": round(float(array.max()), 2),
        "n": int(array.size),
    }
