"""派生量：从已抓到的数据**自己算**出来的数值。

每一条都必须带：``value`` / ``unit`` / ``method`` / ``formula`` / ``basis``（指回 fact_pack 路径）
/ ``confidence: "推断（自算）"`` / ``caveats``。前端与解释层必须把它标成「自算」，
不得与观测（observed）或模式预报（forecast）混在一起，更不构成预报结论。

目前四条：

1. **海拔订正气温** —— 标准大气递减率，把机场实况换算到目标海拔；
2. **体感温度（风寒）** —— Environment Canada 的风寒指数，仅在 T≤10 °C 且风速≥4.8 km/h 时给值；
3. **850hPa 估算高度与 850–500hPa 递减率** —— 用 500hPa 高度 + 850/500 温度做静力学厚度反算；
4. **3 小时变压倾向** —— 由 METAR 历史序列得出，解读为「加压/减压」。
"""

from __future__ import annotations

import math
from typing import Any

# 干空气气体常数与重力加速度
R_DRY = 287.05
G = 9.80665
KELVIN = 273.15

STANDARD_LAPSE_C_PER_KM = 6.5
MIN_ELEVATION_DELTA_M = 300.0
CONFIDENCE = "推断（自算）"

# 风寒指数适用范围（Environment Canada）
WIND_CHILL_MAX_TEMP_C = 10.0
WIND_CHILL_MIN_WIND_KMH = 4.8


def _item(
    value: float,
    unit: str,
    method: str,
    formula: str,
    basis: list[str],
    caveats: list[str],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "value": round(float(value), 1),
        "unit": unit,
        "method": method,
        "formula": formula,
        "basis": basis,
        "confidence": CONFIDENCE,
        "caveats": caveats,
        **extra,
    }


def adjust_temperature_to_elevation(
    temp_c: float | None,
    station_elevation_m: float | None,
    site_elevation_m: float | None,
    *,
    lapse_c_per_km: float = STANDARD_LAPSE_C_PER_KM,
) -> dict[str, Any] | None:
    """按标准递减率把站点气温换算到目标海拔。条件不足返回 ``None``（不猜）。"""
    if temp_c is None or station_elevation_m is None or site_elevation_m is None:
        return None
    delta_m = float(site_elevation_m) - float(station_elevation_m)
    if abs(delta_m) < MIN_ELEVATION_DELTA_M:
        return None

    adjusted = float(temp_c) - lapse_c_per_km * delta_m / 1000.0
    return {
        "temp_c": round(adjusted, 1),
        "observed_station_temp_c": float(temp_c),
        "elevation_delta_m": round(delta_m, 0),
        "lapse_rate_c_per_km": lapse_c_per_km,
        "method": "标准大气温度递减率",
        "formula": "T_site = T_station − 6.5 °C/km × Δh",
        "confidence": CONFIDENCE,
        "caveats": [
            "只修正海拔差，未修正站点与目标地的水平距离差异",
            "未考虑逆温、辐射降温、山谷冷池等局地效应",
            "不可替代观测，也不构成预报结论",
        ],
    }


def wind_chill_c(temp_c: float | None, wind_ms: float | None) -> dict[str, Any] | None:
    """风寒指数（°C）。超出适用范围返回 ``None``，不硬算。"""
    if temp_c is None or wind_ms is None:
        return None
    wind_kmh = float(wind_ms) * 3.6
    if temp_c > WIND_CHILL_MAX_TEMP_C or wind_kmh < WIND_CHILL_MIN_WIND_KMH:
        return None
    v16 = wind_kmh**0.16
    value = 13.12 + 0.6215 * float(temp_c) - 11.37 * v16 + 0.3965 * float(temp_c) * v16
    return _item(
        value,
        "°C",
        "风寒指数（体感温度）",
        "13.12 + 0.6215T − 11.37V^0.16 + 0.3965T·V^0.16（T 为 °C，V 为 km/h）",
        ["observed.temp_c", "observed.wind_speed_ms"],
        [
            "仅适用于气温 ≤10 °C、风速 ≥4.8 km/h 的情形",
            "未考虑湿度与日照；有风时体感低于气温",
            "是换算值，不是观测记录，也不是预报",
        ],
        wind_kmh=round(wind_kmh, 1),
    )


def dewpoint_depression_c(temp_c: float | None, dewpoint_c: float | None) -> dict[str, Any] | None:
    """露点差（T − Td），用来判断干燥程度。"""
    if temp_c is None or dewpoint_c is None:
        return None
    depression = float(temp_c) - float(dewpoint_c)
    if depression < 2:
        label = "接近饱和（可能起雾/低云）"
    elif depression < 5:
        label = "偏潮湿"
    elif depression < 10:
        label = "适中"
    else:
        label = "干燥"
    return {
        "value": round(depression, 1),
        "unit": "°C",
        "method": "露点差",
        "formula": "T − Td",
        "label": label,
        "basis": ["observed.temp_c", "observed.dewpoint_c"],
        "confidence": CONFIDENCE,
        "caveats": ["露点差只反映近地面湿度，不代表云底高度"],
    }


def thickness_and_lapse_rate(
    h500_m: float | None, t500_c: float | None, t850_c: float | None
) -> dict[str, Any] | None:
    """用 500hPa 高度与 850/500 温度反算厚度、850hPa 高度与层结递减率。

    静力学方程：``Z500 − Z850 = (R·Tv/g)·ln(850/500)``，
    平均虚温用 (T850+T500)/2 近似（忽略水汽，因此只算「推断」）。
    """
    if h500_m is None or t500_c is None or t850_c is None:
        return None

    tv_mean = ((float(t850_c) + KELVIN) + (float(t500_c) + KELVIN)) / 2.0
    thickness = R_DRY * tv_mean / G * math.log(850.0 / 500.0)
    h850 = float(h500_m) - thickness
    lapse = (float(t850_c) - float(t500_c)) / (thickness / 1000.0)

    if lapse < 5.0:
        stability = "层结较稳定"
    elif lapse < 7.0:
        stability = "接近中性（条件性不稳定边界）"
    else:
        stability = "层结不稳定"

    return {
        "value": round(lapse, 1),
        "unit": "°C/km",
        "method": "静力学厚度反算 + 850–500hPa 递减率",
        "formula": "ΔZ = R·Tv/g·ln(850/500)；Γ = (T850 − T500)/ΔZ",
        "thickness_500_850_m": round(thickness, 0),
        "h850_estimated_m": round(h850, 0),
        "h500_observed_m": round(float(h500_m), 0),
        "mean_virtual_temp_k": round(tv_mean, 1),
        "stability": stability,
        "basis": [
            "synoptic.h500_geopotential_m",
            "synoptic.t850_c",
            "synoptic.t500_c",
        ],
        "confidence": CONFIDENCE,
        "caveats": [
            "平均虚温用 (T850+T500)/2 近似，未计水汽与逆温层",
            "h850 是反算值，若有探空/模式 850hPa 高度应以其为准",
            "递减率只代表 850–500hPa 这一层，不代表整层大气",
        ],
    }


def pressure_tendency(delta_3h_hpa: float | None) -> dict[str, Any] | None:
    """3 小时变压的定性解读。"""
    if delta_3h_hpa is None:
        return None
    delta = float(delta_3h_hpa)
    if delta >= 1.5:
        label = "明显加压，高压增强，天气通常转好"
    elif delta <= -1.5:
        label = "明显减压，低压或槽接近，天气可能转坏"
    else:
        label = "气压变化不大"
    return {
        "value": round(delta, 1),
        "unit": "hPa/3h",
        "method": "3 小时变压倾向",
        "formula": "P(t) − P(t−3h)",
        "label": label,
        "basis": ["observed.pressure_trend_3h_hpa"],
        "confidence": CONFIDENCE,
        "caveats": ["单站变压只说明局地气压变化，不等于天气系统移动速度"],
    }
