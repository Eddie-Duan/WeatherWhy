"""fact_pack 组装：编排 providers → 一份带出处的事实包（**不经 LLM**）。

这是全项目的核心交付物：地图上的数值和聊天里的解释必须来自同一份事实，
所以 ``fact_pack_id``（内容哈希）同时进日志与解释层，便于回溯。

M1 覆盖 ``location / observed / trend_24h / forecast / provenance``；
``synoptic / climate / warnings`` 在 M2 填入，未实现时一律 ``null`` 并进 ``missing``。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from skylens.cache.store import TTLCache
from skylens.net import create_client
from skylens.providers import geocode as geocode_provider
from skylens.providers import metar as metar_provider
from skylens.providers import open_meteo as open_meteo_provider
from skylens.settings import Settings, get_settings

SCHEMA_VERSION = "1.0"
SHANGHAI = ZoneInfo("Asia/Shanghai")
MISSING_M2 = "synoptic / climate / warnings（M2 提供）"

Geocoder = Callable[..., Awaitable[dict[str, Any]]]
Forecaster = Callable[..., Awaitable[dict[str, Any]]]
Observer = Callable[..., Awaitable[dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def jsonable(value: Any) -> Any:
    """递归把 NaN/Inf 换成 None：fact_pack 必须是合法 JSON，缺就写 null。"""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def content_id(payload: dict[str, Any]) -> str:
    """fact_pack_id：除自身与生成时刻之外内容的哈希。"""
    body = {k: v for k, v in payload.items() if k not in ("fact_pack_id", "generated_at")}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


async def _timed(
    name: str, coro: Awaitable[dict[str, Any]], deadline: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=deadline)
    except Exception as exc:
        result = {"error": str(exc), "provider": name}
    latency = int((time.perf_counter() - started) * 1000)
    entry = {"name": name, "ok": "error" not in result, "latency_ms": latency}
    if "error" in result:
        entry["error"] = result["error"]
    return result, entry


async def build_fact_pack(
    query: str | None = None,
    *,
    lat: float | None = None,
    lon: float | None = None,
    name: str | None = None,
    days: int = 7,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
    geocoder: Geocoder | None = None,
    forecaster: Forecaster | None = None,
    observer: Observer | None = None,
) -> dict[str, Any]:
    """给定地名（或坐标）产出 fact_pack。取数失败只记 ``missing``，不抛异常。"""
    settings = settings or get_settings()
    if cache is None:
        cache = TTLCache(settings.ensure_cache_dir() / "http")
    geocoder = geocoder or geocode_provider.geocode
    forecaster = forecaster or open_meteo_provider.fetch_daily_forecast
    observer = observer or metar_provider.fetch_nearest

    own_client = client is None
    client = client or create_client(settings)
    try:
        if lat is None or lon is None:
            if not query:
                return {"error": "missing_input", "detail": "需要 query 或 lat/lon"}
            location, geo_entry = await _timed(
                "geocode",
                geocoder(query, settings=settings, cache=cache, client=client),
                settings.request_deadline_s,
            )
            if "error" in location:
                return {
                    "error": location["error"],
                    "query": query,
                    "detail": location.get("detail"),
                }
        else:
            location = {
                "query": query or name or f"{lat:.4f},{lon:.4f}",
                "name": name or f"{lat:.4f},{lon:.4f}",
                "admin": "",
                "lat": lat,
                "lon": lon,
                "elevation_m": None,
                "timezone": "Asia/Shanghai",
                "geocode_source": "coordinates",
                "geocode_confidence": 1.0,
                "geocode_candidates": [],
            }
            geo_entry = {"name": "geocode", "ok": True, "latency_ms": 0, "skipped": "coordinates"}

        elevation = location.get("elevation_m")
        forecast_coro = forecaster(
            location["lat"],
            location["lon"],
            days=days,
            settings=settings,
            cache=cache,
            client=client,
        )
        observed_coro = observer(
            location["lat"],
            location["lon"],
            place=location.get("name") or "",
            elevation_m=elevation,
            settings=settings,
            cache=cache,
            client=client,
        )
        (forecast, forecast_entry), (observed, observed_entry) = await asyncio.gather(
            _timed("open_meteo", forecast_coro, settings.request_deadline_s),
            _timed("metar", observed_coro, settings.request_deadline_s),
        )

        providers = [geo_entry, forecast_entry, observed_entry]
        missing: list[str] = []
        notes: list[str] = []

        if location.get("elevation_m") is None and forecast.get("elevation_m") is not None:
            location["elevation_m"] = forecast["elevation_m"]
            notes.append("海拔取自 Open-Meteo 格点（地理编码源未提供）")

        if "error" in forecast:
            missing.append(f"多模式预报（{forecast['error']}）")
        if not observed.get("available"):
            missing.append("本地实况（附近无可用 METAR）")
        missing.append(MISSING_M2)
        notes.append("M1 阶段：synoptic / climate / warnings 恒为 null")

        if not observed.get("available") and observed.get("error"):
            notes.append(f"METAR：{observed['error']}")

        pack: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "fact_pack_id": "",
            "generated_at": _now().isoformat(timespec="seconds"),
            "location": location,
            "observed": {k: v for k, v in observed.items() if k not in ("trend_24h", "provider")},
            "trend_24h": observed.get("trend_24h"),
            "forecast": (
                None
                if "error" in forecast
                else {
                    "models": forecast.get("models", []),
                    "elevation_m": forecast.get("elevation_m"),
                    "daily": forecast.get("daily", []),
                    "agreement": forecast.get("agreement", {}),
                }
            ),
            "synoptic": None,
            "climate": None,
            "warnings": [],
            "provenance": {
                "providers": providers,
                "missing": missing,
                "notes": notes,
            },
        }
        pack = jsonable(pack)
        pack["fact_pack_id"] = content_id(pack)
        return pack
    finally:
        if own_client:
            await client.aclose()
