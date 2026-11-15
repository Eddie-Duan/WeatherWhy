"""单位换算：全项目唯一允许做换算的地方。

provider 只做「抓取 + 打 Sourced」，换算集中在此，避免旧仓把英制写死在请求参数里的债。
内部统一公制：°C / mm / m·s⁻¹ / hPa / m。
"""

from __future__ import annotations

INHG_TO_HPA = 33.8638866667
MPH_TO_MS = 0.44704
KMH_TO_MS = 1.0 / 3.6
KT_TO_MS = 0.514444
FT_TO_M = 0.3048
MILE_TO_M = 1609.344
INCH_TO_MM = 25.4


def f_to_c(value: float) -> float:
    return (float(value) - 32.0) * 5.0 / 9.0


def c_to_f(value: float) -> float:
    return float(value) * 9.0 / 5.0 + 32.0


def mph_to_ms(value: float) -> float:
    return float(value) * MPH_TO_MS


def kmh_to_ms(value: float) -> float:
    return float(value) * KMH_TO_MS


def knots_to_ms(value: float) -> float:
    return float(value) * KT_TO_MS


def inhg_to_hpa(value: float) -> float:
    return float(value) * INHG_TO_HPA


def hpa_to_inhg(value: float) -> float:
    return float(value) / INHG_TO_HPA


def ft_to_m(value: float) -> float:
    return float(value) * FT_TO_M


def mile_to_m(value: float) -> float:
    return float(value) * MILE_TO_M


def inch_to_mm(value: float) -> float:
    return float(value) * INCH_TO_MM


def wind_speed_to_ms(value: float, unit: str) -> float:
    """按单位名把风速换到 m/s：``ms`` / ``mph`` / ``kmh`` / ``kt``。"""
    normalised = unit.strip().lower()
    converters = {
        "ms": lambda v: float(v),
        "m/s": lambda v: float(v),
        "mph": mph_to_ms,
        "kmh": kmh_to_ms,
        "km/h": kmh_to_ms,
        "kt": knots_to_ms,
        "kts": knots_to_ms,
        "knot": knots_to_ms,
        "knots": knots_to_ms,
    }
    try:
        return converters[normalised](value)
    except KeyError as exc:
        raise ValueError(f"未知风速单位：{unit!r}") from exc


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    """缺失一律 None，不用默认值填补（fact_pack 契约）。"""
    if value is None:
        return None
    return round(float(value), digits)
