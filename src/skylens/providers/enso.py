"""ENSO：NOAA CPC 的 ONI 月表（公有领域，日频更新，缓存 7 天）。

``oni.ascii.txt`` 是定宽文本：``SEAS YR TOTAL ANOM``，例如 ``ASO 2026 29.23 2.46``。
Onset 判据用 NOAA 的 ±0.5 °C：≥ +0.5 El Niño、≤ -0.5 La Niña，其余为中性。
季节三字母取中间月作为 ``month``（ASO → 8 月），便于与其他月频数据对齐。
"""

from __future__ import annotations

from typing import Any

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
SEASON_MONTH = {
    "DJF": 1,
    "JFM": 2,
    "FMA": 3,
    "MAM": 4,
    "AMJ": 5,
    "MJJ": 6,
    "JJA": 7,
    "JAS": 8,
    "ASO": 9,
    "SON": 10,
    "OND": 11,
    "NDJ": 12,
}
ONI_THRESHOLD = 0.5


def parse_oni(text: str) -> dict[str, Any] | None:
    """取最后一行有效记录。表头或残缺行跳过，不猜。"""
    latest: dict[str, Any] | None = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        season, year, _total, anomaly = parts
        if season not in SEASON_MONTH:
            continue
        try:
            latest = {
                "season": season,
                "year": int(year),
                "month": f"{int(year):04d}-{SEASON_MONTH[season]:02d}",
                "oni": float(anomaly),
            }
        except ValueError:
            continue
    return latest


def phase(oni: float) -> str:
    if oni >= ONI_THRESHOLD:
        return "El Niño"
    if oni <= -ONI_THRESHOLD:
        return "La Niña"
    return "中性"


async def fetch_enso(
    *,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """最新 ONI 与 ENSO 相位。失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    own_client = client is None
    client = client or create_client(settings)
    try:
        key = make_key(ONI_URL)
        text = cache_get(cache, key, registry.TTLS.enso)
        if text is None:
            resp = await client.get(ONI_URL)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "provider": "enso"}
            text = resp.text
            cache_set(cache, key, text)

        latest = parse_oni(text)
        if latest is None:
            return {"error": "ONI 表中无有效记录", "provider": "enso"}
        return {
            "provider": "enso",
            "phase": phase(latest["oni"]),
            "oni": latest["oni"],
            "month": latest["month"],
            "season": latest["season"],
            "source": "NOAA CPC ONI",
            "source_url": ONI_URL,
            "threshold": ONI_THRESHOLD,
        }
    except Exception as exc:  # provider 不抛异常出界
        return {"error": str(exc), "provider": "enso"}
    finally:
        if own_client:
            await client.aclose()
