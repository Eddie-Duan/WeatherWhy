"""中文地名优先的地理编码：和风天气 GeoAPI → Nominatim → Open-Meteo。

**实测结论（2026-11-15）**：Open-Meteo geocoding 对「明安图镇」「正镶白旗」这类
旗县级中文地名**返回空结果**，对本项目基本不可用；Nominatim 反而能精确命中
（``明安图镇 → 42.2984, 115.0014, 正镶白旗/锡林郭勒盟/内蒙古自治区``）。
因此这里把 Nominatim 放在 Open-Meteo 前面，与 ``docs/MIGRATION.md`` §2.3 的建议顺序不同，
理由是实测可用性，而不是偏好。

所有候选都返回（``limit`` 提到 5），不做「只取第一条」的静默猜测。
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import Any

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.net import create_client
from skylens.providers import qweather, registry
from skylens.settings import Settings

_CJK = ("\u4e00", "\u9fff")


def _has_cjk(text: str) -> bool:
    return any(_CJK[0] <= ch <= _CJK[1] for ch in text)


def _score(query: str, name: str, rank: int, base: float) -> float:
    """候选分：名称相似度 × 来源基线 × 名次衰减。"""
    similarity = difflib.SequenceMatcher(None, query, name).ratio()
    return round(min(0.99, base * (0.6 + 0.4 * similarity) * (1.0 - 0.08 * rank)), 2)


def _candidate(
    name: str, admin: str, lat: float, lon: float, elevation: float | None, score: float
):
    return {
        "name": name,
        "admin": admin,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "elevation_m": elevation,
        "score": score,
    }


def _from_qweather(payload: Mapping, query: str) -> list[dict[str, Any]]:
    locations = payload.get("location") or []
    out = []
    for rank, item in enumerate(locations[:5]):
        name = item.get("name") or query
        admin = " ".join(
            part for part in (item.get("adm1"), item.get("adm2"), item.get("name")) if part
        )
        out.append(
            _candidate(
                name=name,
                admin=admin,
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                elevation=None,
                score=_score(query, name, rank, base=0.95),
            )
        )
    return out


def _from_nominatim(payload: list[Mapping], query: str) -> list[dict[str, Any]]:
    out = []
    for rank, item in enumerate(payload[:5]):
        address = item.get("address") or {}
        name = item.get("name") or address.get("town") or address.get("county") or query
        admin_parts = [
            address.get(key)
            for key in ("state", "city", "county", "town", "district")
            if address.get(key) and address.get(key) != name
        ]
        out.append(
            _candidate(
                name=name,
                admin=" ".join(dict.fromkeys(admin_parts)),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                elevation=None,
                score=_score(query, name, rank, base=0.85),
            )
        )
    return out


def _from_open_meteo(payload: Mapping, query: str) -> list[dict[str, Any]]:
    results = payload.get("results") or []
    base = 0.6 if _has_cjk(query) else 0.8  # 实测：中文县级地名常落空或跑偏
    out = []
    for rank, item in enumerate(results[:5]):
        name = item.get("name") or query
        admin = " ".join(
            part for part in (item.get("country"), item.get("admin1"), item.get("admin2")) if part
        )
        out.append(
            _candidate(
                name=name,
                admin=admin,
                lat=float(item["latitude"]),
                lon=float(item["longitude"]),
                elevation=item.get("elevation"),
                score=_score(query, name, rank, base=base),
            )
        )
    return out


async def geocode(
    query: str,
    *,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """地名 → fact_pack 的 ``location`` 块；失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    own_client = client is None
    client = client or create_client(settings)
    try:
        candidates: list[dict[str, Any]] = []
        source = ""

        if settings.qweather_key is not None:
            url = qweather.geo_url(settings)
            params = {
                "location": query,
                "key": settings.qweather_key.get_secret_value(),
                "lang": "zh",
                "number": 5,
            }
            key = make_key(url, {**params, "key": "<redacted>"})
            payload = cache_get(cache, key, registry.TTLS.geocode)
            if payload is None:
                resp = await client.get(url, params=params)
                payload = resp.json() if resp.status_code == 200 else {}
                cache_set(cache, key, payload)
            if payload.get("location"):
                candidates, source = _from_qweather(payload, query), "qweather"

        if not candidates:
            params = {
                "q": query,
                "format": "jsonv2",
                "limit": 5,
                "accept-language": "zh",
                "addressdetails": 1,
            }
            key = make_key(registry.NOMINATIM_SEARCH, params)
            payload = cache_get(cache, key, registry.TTLS.geocode)
            if payload is None:
                resp = await client.get(registry.NOMINATIM_SEARCH, params=params)
                payload = resp.json() if resp.status_code == 200 else []
                cache_set(cache, key, payload)
            if payload:
                candidates, source = _from_nominatim(payload, query), "nominatim"

        if not candidates:
            params = {"name": query, "count": 5, "language": "zh", "format": "json"}
            key = make_key(registry.OPEN_METEO_GEOCODING, params)
            payload = cache_get(cache, key, registry.TTLS.geocode)
            if payload is None:
                resp = await client.get(registry.OPEN_METEO_GEOCODING, params=params)
                payload = resp.json() if resp.status_code == 200 else {}
                cache_set(cache, key, payload)
            if payload.get("results"):
                candidates, source = _from_open_meteo(payload, query), "open_meteo"

        if not candidates:
            return {"error": "geocode_not_found", "query": query}

        best = max(candidates, key=lambda c: c["score"])
        return {
            "query": query,
            "name": best["name"],
            "admin": best["admin"],
            "lat": best["lat"],
            "lon": best["lon"],
            "elevation_m": best["elevation_m"],
            "timezone": "Asia/Shanghai",
            "geocode_source": source,
            "geocode_confidence": best["score"],
            "geocode_candidates": candidates,
        }
    except Exception as exc:  # provider 不抛异常出界
        return {"error": "geocode_failed", "query": query, "detail": str(exc)}
    finally:
        if own_client:
            await client.aclose()
