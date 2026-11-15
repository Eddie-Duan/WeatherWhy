"""中文文案与分级阈值表：术语、等级、单位的唯一来源。

阈值取自旧仓 ``calculate_model_agreement``（spread < 3 / < 7），并按要素分档：
降水用 mm，阈值自然不同（0.4 mm 的离散度在降水里已经算很集中）。
"""

from __future__ import annotations

from typing import Literal

Level = Literal["高", "中", "低"]

LEVEL_HIGH: Level = "高"
LEVEL_MID: Level = "中"
LEVEL_LOW: Level = "低"

# 要素 → (高/中分界, 中/低分界)。spread < 下限 判「高」，< 上限 判「中」，否则「低」。
AGREEMENT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "temperature": (3.0, 7.0),  # °C
    "precipitation": (1.0, 5.0),  # mm
    "wind": (3.0, 7.0),  # m/s
}

# 解释层 confidence 只用这三档。
CONFIDENCE_LEVELS: tuple[Level, ...] = (LEVEL_LOW, LEVEL_MID, LEVEL_HIGH)

# 三层信息强制区分：观测 / 预报 / 推断（UI 配色不同）。
EVIDENCE_KINDS: tuple[str, ...] = ("观测", "预报", "推断")

REPRESENTATIVENESS_LEVELS: tuple[Level, ...] = (LEVEL_LOW, LEVEL_MID, LEVEL_HIGH)

_COMPASS_8 = ("北", "东北", "东", "东南", "南", "西南", "西", "西北")

# 月份 → 气候季节（中文习惯：11 月是初冬，不是深秋）
_SEASONS = {
    1: "隆冬",
    2: "冬末",
    3: "初春",
    4: "春",
    5: "春末",
    6: "初夏",
    7: "盛夏",
    8: "夏末",
    9: "初秋",
    10: "秋",
    11: "初冬",
    12: "隆冬",
}


def season_label(month: int) -> str:
    return _SEASONS.get(month, "初冬")


def agreement_level(variable: str, spread: float) -> Level:
    """把离散度换成「高/中/低」一致性等级。未知要素按风处理并在文档里说明。"""
    high_below, mid_below = AGREEMENT_THRESHOLDS.get(variable, AGREEMENT_THRESHOLDS["wind"])
    if spread < high_below:
        return LEVEL_HIGH
    if spread < mid_below:
        return LEVEL_MID
    return LEVEL_LOW


def agreement(variable: str, spread: float) -> dict[str, str | float]:
    """fact_pack ``forecast.agreement`` 的最小单元：``{"level": ..., "spread": ...}``。"""
    return {"level": agreement_level(variable, spread), "spread": round(float(spread), 2)}


def wind_direction_label(degrees: float | None) -> str | None:
    """风向角（气象约定：风的来向）→ 八方位中文名。"""
    if degrees is None:
        return None
    return _COMPASS_8[int((float(degrees) % 360) / 45.0 + 0.5) % 8]
