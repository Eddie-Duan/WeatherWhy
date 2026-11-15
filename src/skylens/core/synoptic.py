"""环流形势：把 500/850hPa 数值 + 天气图整理成 ``synoptic`` 块，并给出**确定性**的环流型判定。

``pattern`` 是规则推的，不是模型写的：每条结论都带 ``basis`` 指回 fact_pack 里的真实路径，
``confidence`` 固定为「推断」——它既不是观测也不是预报。

阈值取常用的天气学经验值（500hPa 高度 5400/5600 m、850hPa -10 °C），改动即改文档。
"""

from __future__ import annotations

from typing import Any

from skylens.core import vocab

DEEP_TROUGH_M = 5400.0  # 低于此值视为深槽
RIDGE_M = 5600.0  # 高于此值视为高压脊
COLD_ADVECTION_C = -10.0  # 850hPa 低于此值视为低层冷平流


def flow_label(direction_deg: float | None) -> str | None:
    """850hPa 风向 → 「西北气流 / 偏东气流」这类表述（气象约定：风的来向）。"""
    label = vocab.wind_direction_label(direction_deg)
    if label is None:
        return None
    if label in {"东", "南", "西", "北"}:  # 正方位习惯说「偏东气流」
        return f"偏{label}气流"
    return f"{label}气流"


def classify_pattern(synoptic: dict[str, Any]) -> dict[str, Any]:
    """规则化环流型判定。数据缺失时如实说明，不编造。"""
    h500 = synoptic.get("h500_geopotential_m")
    t850 = synoptic.get("t850_c")
    wind_dir = synoptic.get("wind850_dir_deg")
    wind_speed = synoptic.get("wind850_speed_ms")

    if h500 is None and t850 is None:
        return {
            "label": "环流资料缺失，未做形势判定",
            "confidence": "推断",
            "basis": [],
        }

    parts: list[str] = []
    basis: list[str] = []

    if h500 is not None:
        basis.append("synoptic.h500_geopotential_m")
        if h500 < DEEP_TROUGH_M:
            parts.append("500hPa 深槽控制")
        elif h500 > RIDGE_M:
            parts.append("500hPa 高压脊控制")
        else:
            parts.append("500hPa 平直西风")

    if wind_dir is not None:
        basis.append("synoptic.wind850_dir_deg")
        flow = flow_label(wind_dir)
        if flow:
            parts.append(f"850hPa {flow}")

    if t850 is not None:
        basis.append("synoptic.t850_c")
        if t850 <= COLD_ADVECTION_C:
            parts.append("低层冷平流明显")

    if wind_speed is not None:
        basis.append("synoptic.wind850_speed_ms")
        if wind_speed >= 12.0:
            parts.append("850hPa 风速偏大")

    return {
        "label": "，".join(parts) if parts else "环流形势无明显特征",
        "confidence": "推断",
        "basis": basis,
    }


def build_synoptic(
    pressure: dict[str, Any], charts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """组装 ``synoptic`` 块；``h500_anomaly_m`` 需要气候态，M2 阶段留 null。"""
    synoptic: dict[str, Any] = {
        "h500_geopotential_m": pressure.get("h500_geopotential_m"),
        "h500_anomaly_m": None,  # 气候态需 data.cma.cn / ERA5，见 README 偏差表
        "t500_c": pressure.get("t500_c"),
        "t850_c": pressure.get("t850_c"),
        "wind850_dir_deg": pressure.get("wind850_dir_deg"),
        "wind850_speed_ms": pressure.get("wind850_speed_ms"),
        "valid_time": pressure.get("valid_time"),
        "source": "Open-Meteo pressure-level",
        "source_url": pressure.get("source_url"),
        "charts": charts or [],
    }
    synoptic["pattern"] = classify_pattern(synoptic)
    return synoptic
