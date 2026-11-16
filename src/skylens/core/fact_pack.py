"""fact_pack 组装：编排 providers → 一份带出处的事实包（**不经 LLM**）。

这是全项目的核心交付物：地图上的数值和聊天里的解释必须来自同一份事实，
所以 ``fact_pack_id``（内容哈希）同时进日志与解释层，便于回溯。

M1 覆盖 ``location / observed / trend_24h / forecast / provenance``；
M2 补 ``synoptic``（500/850hPa + 天气图 + 环流型规则判定）与 ``climate.enso``；
``warnings`` 需和风天气 key，留待 M4，未接入时一律 ``null`` / 空数组并进 ``missing``。
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
from skylens.core import derive, vocab
from skylens.core.derive import adjust_temperature_to_elevation
from skylens.core.synoptic import build_synoptic
from skylens.net import create_client
from skylens.providers import charts as charts_provider
from skylens.providers import enso as enso_provider
from skylens.providers import geocode as geocode_provider
from skylens.providers import metar as metar_provider
from skylens.providers import open_meteo as open_meteo_provider
from skylens.providers import qweather as qweather_provider
from skylens.settings import Settings, get_settings

SCHEMA_VERSION = "1.0"
SHANGHAI = ZoneInfo("Asia/Shanghai")

Geocoder = Callable[..., Awaitable[dict[str, Any]]]
Forecaster = Callable[..., Awaitable[dict[str, Any]]]
Observer = Callable[..., Awaitable[dict[str, Any]]]
Loader = Callable[..., Awaitable[dict[str, Any]]]


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
    pressure_loader: Loader | None = None,
    chart_loader: Loader | None = None,
    enso_loader: Loader | None = None,
    warnings_loader: Loader | None = None,
    local_loader: Loader | None = None,
) -> dict[str, Any]:
    """给定地名（或坐标）产出 fact_pack。取数失败只记 ``missing``，不抛异常。"""
    settings = settings or get_settings()
    if cache is None:
        cache = TTLCache(settings.ensure_cache_dir() / "http")
    geocoder = geocoder or geocode_provider.geocode
    forecaster = forecaster or open_meteo_provider.fetch_daily_forecast
    observer = observer or metar_provider.fetch_nearest
    pressure_loader = pressure_loader or open_meteo_provider.fetch_pressure_levels
    chart_loader = chart_loader or charts_provider.fetch_charts
    enso_loader = enso_loader or enso_provider.fetch_enso
    warnings_loader = warnings_loader or qweather_provider.fetch_warnings
    local_loader = local_loader or qweather_provider.fetch_now

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
        pressure_coro = pressure_loader(
            location["lat"],
            location["lon"],
            settings=settings,
            cache=cache,
            client=client,
        )
        charts_coro = chart_loader(settings=settings, cache=cache, client=client)
        enso_coro = enso_loader(settings=settings, cache=cache, client=client)
        warnings_coro = warnings_loader(
            location["lat"],
            location["lon"],
            settings=settings,
            cache=cache,
            client=client,
        )
        local_coro = local_loader(
            location["lat"],
            location["lon"],
            settings=settings,
            cache=cache,
            client=client,
        )
        (
            (forecast, forecast_entry),
            (observed, observed_entry),
            (pressure, pressure_entry),
            (
                charts,
                charts_entry,
            ),
            (enso, enso_entry),
            (alerts, alerts_entry),
            (local_now, local_entry),
        ) = await asyncio.gather(
            _timed("open_meteo", forecast_coro, settings.request_deadline_s),
            _timed("metar", observed_coro, settings.request_deadline_s),
            _timed("open_meteo_pressure", pressure_coro, settings.request_deadline_s),
            _timed("charts", charts_coro, settings.request_deadline_s),
            _timed("enso", enso_coro, settings.request_deadline_s),
            _timed("qweather", warnings_coro, settings.request_deadline_s),
            _timed("qweather_current", local_coro, settings.request_deadline_s),
        )

        providers = [
            geo_entry,
            forecast_entry,
            observed_entry,
            pressure_entry,
            charts_entry,
            enso_entry,
            alerts_entry,
            local_entry,
        ]
        missing: list[str] = []
        notes: list[str] = []

        if location.get("geocode_note"):
            notes.append(str(location["geocode_note"]))
        if location.get("geocode_attempt_errors"):
            notes.append(
                "地理编码降级："
                + "；".join(
                    f"{item['source']} {item['error']}"
                    for item in location["geocode_attempt_errors"]
                )
            )

        if location.get("elevation_m") is None and forecast.get("elevation_m") is not None:
            location["elevation_m"] = forecast["elevation_m"]
            notes.append("海拔取自 Open-Meteo 格点（地理编码源未提供）")

        if observed.get("available"):
            adjustment = adjust_temperature_to_elevation(
                observed.get("temp_c"),
                (observed.get("station") or {}).get("elevation_m"),
                location.get("elevation_m"),
            )
            if adjustment is not None:
                observed["temp_adjusted"] = adjustment
                notes.append("观测气温已按标准递减率订正到站点海拔（标注为推断，不替换原始观测）")

        if "error" in forecast:
            missing.append(f"多模式预报（{forecast['error']}）")
        if not observed.get("available"):
            missing.append("本地实况（附近无可用 METAR）")
        if "error" in pressure:
            missing.append(f"500/850hPa 环流（{pressure['error']}）")
        if "error" in charts:
            missing.append(f"天气图（{charts['error']}）")
        if "error" in enso:
            missing.append(f"ENSO 指数（{enso['error']}）")
        if not alerts.get("available"):
            reason = alerts.get("error") or alerts.get("reason") or "未知原因"
            missing.append(f"官方预警（{reason}）")
        missing.append("h500 距平与气候态（需 data.cma.cn / ERA5，未实现）")
        notes.append("离散度为多模式 p10–p90（模式间），成员级 ensemble spread 待 M2 后续接入")
        if not observed.get("available") and observed.get("error"):
            notes.append(f"METAR：{observed['error']}")

        synoptic = build_synoptic(
            {} if "error" in pressure else pressure,
            charts.get("charts") or [],
        )
        derived: dict[str, Any] = {}
        if observed.get("available"):
            for name, item in (
                (
                    "wind_chill_c",
                    derive.wind_chill_c(observed.get("temp_c"), observed.get("wind_speed_ms")),
                ),
                (
                    "dewpoint_depression_c",
                    derive.dewpoint_depression_c(
                        observed.get("temp_c"), observed.get("dewpoint_c")
                    ),
                ),
                (
                    "pressure_tendency",
                    derive.pressure_tendency(observed.get("pressure_trend_3h_hpa")),
                ),
            ):
                if item is not None:
                    derived[name] = item
        thickness = derive.thickness_and_lapse_rate(
            pressure.get("h500_geopotential_m"),
            pressure.get("t500_c"),
            pressure.get("t850_c"),
        )
        if thickness is not None:
            derived["thickness_850_500"] = thickness
        if derived:
            notes.append("derived 为本项目按公式自算的推断值（每项都带 method/formula/caveats）")

        climate: dict[str, Any] = {
            "season": vocab.season_label(_now().month),
            "enso": (
                None
                if "error" in enso
                else {
                    "phase": enso.get("phase"),
                    "oni": enso.get("oni"),
                    "month": enso.get("month"),
                    "source": enso.get("source"),
                    "source_url": enso.get("source_url"),
                }
            ),
            "climate_normal": None,
        }

        if local_now.get("available"):
            observed["local"] = {k: v for k, v in local_now.items() if k not in ("provider",)}
            notes.append("observed.local 为和风格点实况（非站点观测），与机场 METAR 需分开解读")
        elif local_now.get("error") or local_now.get("reason"):
            notes.append(
                "本地格点实况不可用：" + str(local_now.get("error") or local_now.get("reason"))
            )

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
            "synoptic": synoptic,
            "climate": climate,
            "derived": derived or None,
            "derived_note": (
                "本块为项目自行计算的推断值（非观测、非官方预报）；每项含 method/formula/caveats"
                if derived
                else None
            ),
            "warnings": alerts.get("warnings") or [],
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
