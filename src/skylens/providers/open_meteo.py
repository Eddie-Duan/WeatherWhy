"""Open-Meteo：多模式逐日预报 + 离散度（fact_pack ``forecast`` 块）。

旧仓 ``weather_api.py`` 的三个硬伤在这里改掉：请求按需字段、公制、endpoint 走 registry。
多模式用一次请求 + ``models=a,b,c`` 拿齐，键名形如 ``temperature_2m_max_ecmwf_ifs025``；
每个变量在模式之间算 mean/p10/p90/spread，即「多模式一致吗」。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.core import stats
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

# fact_pack 字段 ← Open-Meteo daily 变量名
DAILY_VARIABLES: dict[str, str] = {
    "temp_max": "temperature_2m_max",
    "temp_min": "temperature_2m_min",
    "precip_mm": "precipitation_sum",
    "wind_max_ms": "wind_speed_10m_max",
}


def _clean(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def build_daily(daily_payload: dict[str, list], models: list[str]) -> list[dict[str, Any]]:
    """把 Open-Meteo 的「模式后缀」键，翻译成 fact_pack 的逐日统计块。"""
    dates: list[str] = daily_payload.get("time") or []
    per_model: list[dict[str, Any]] = []
    for model in models:
        entry: dict[str, Any] = {"model": model, "daily": {}}
        for field, variable in DAILY_VARIABLES.items():
            series = daily_payload.get(f"{variable}_{model}")
            if series is not None:
                entry["daily"][field] = series
        per_model.append(entry)

    out: list[dict[str, Any]] = []
    for index, date in enumerate(dates):
        day: dict[str, Any] = {"date": date}
        for field in DAILY_VARIABLES:
            values = []
            for entry in per_model:
                series = entry["daily"].get(field)
                if series is not None and index < len(series) and series[index] is not None:
                    values.append(float(series[index]))
            if field == "precip_mm":
                # 个别模式会给出 -0.0x 的数值噪音；降水不可能为负，按 0 处理（只夹这一项）
                values = [max(0.0, value) for value in values]
            summary = stats.summarize_values(values)
            day[field] = {k: _clean(v) for k, v in summary.items()}
        out.append(day)
    return out


async def fetch_daily_forecast(
    lat: float,
    lon: float,
    *,
    days: int = 7,
    models: list[str] | None = None,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """多模式逐日预报 + 一致性分级。失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    models = models or registry.ModelRegistry().names
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "daily": ",".join(DAILY_VARIABLES.values()),
        "models": ",".join(models),
        "timezone": "Asia/Shanghai",
        "forecast_days": days,
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }
    own_client = client is None
    client = client or create_client(settings)
    source_url = str(httpx.Request("GET", registry.OPEN_METEO_FORECAST, params=params).url)
    try:
        key = make_key(registry.OPEN_METEO_FORECAST, params)
        payload = cache_get(cache, key, registry.TTLS.forecast)
        if payload is None:
            resp = await client.get(registry.OPEN_METEO_FORECAST, params=params)
            if resp.status_code != 200:
                return {
                    "error": f"HTTP {resp.status_code}",
                    "provider": "open_meteo",
                    "url": source_url,
                }
            payload = resp.json()
            cache_set(cache, key, payload)
        if not payload.get("daily"):
            return {"error": "响应缺少 daily 块", "provider": "open_meteo"}

        daily = build_daily(payload["daily"], models)
        return {
            "provider": "open_meteo",
            "models": models,
            "elevation_m": payload.get("elevation"),
            "timezone": payload.get("timezone", "Asia/Shanghai"),
            "daily": daily,
            "agreement": stats.summarize_forecast_uncertainty(
                daily, basis=f"Open-Meteo 多模式（{len(models)} 个）逐日 p10–p90"
            ),
            "source_url": source_url,
        }
    except Exception as exc:  # provider 不抛异常出界
        return {"error": str(exc), "provider": "open_meteo"}
    finally:
        if own_client:
            await client.aclose()


# fact_pack 字段 ← Open-Meteo pressure-level 小时变量
PRESSURE_VARIABLES: dict[str, str] = {
    "h500_geopotential_m": "geopotential_height_500hPa",
    "t500_c": "temperature_500hPa",
    "t850_c": "temperature_850hPa",
    "wind850_speed_ms": "wind_speed_850hPa",
    "wind850_dir_deg": "wind_direction_850hPa",
}


def pick_nearest_hour(times: list[str], at: datetime) -> int:
    """在小时序列里挑最接近 ``at`` 的下标（离线可测，不依赖当前时间）。"""
    target = at.replace(tzinfo=None)
    best_index, best_gap = 0, None
    for index, stamp in enumerate(times):
        moment = datetime.fromisoformat(stamp)
        gap = abs((moment - target).total_seconds())
        if best_gap is None or gap < best_gap:
            best_index, best_gap = index, gap
    return best_index


async def fetch_pressure_levels(
    lat: float,
    lon: float,
    *,
    at: datetime | None = None,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """500/850hPa 环流背景（成因解释的原料）。失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    at = at or datetime.now(ZoneInfo("Asia/Shanghai"))
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "hourly": ",".join(PRESSURE_VARIABLES.values()),
        "timezone": "Asia/Shanghai",
        "past_days": 1,
        "forecast_days": 2,
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
    }
    own_client = client is None
    client = client or create_client(settings)
    source_url = str(httpx.Request("GET", registry.OPEN_METEO_FORECAST, params=params).url)
    try:
        key = make_key(registry.OPEN_METEO_FORECAST, params)
        payload = cache_get(cache, key, registry.TTLS.pressure_levels)
        if payload is None:
            resp = await client.get(registry.OPEN_METEO_FORECAST, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "provider": "open_meteo_pressure"}
            payload = resp.json()
            cache_set(cache, key, payload)

        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if not times:
            return {"error": "响应缺少 hourly.time", "provider": "open_meteo_pressure"}
        index = pick_nearest_hour(times, at)

        result: dict[str, Any] = {
            "provider": "open_meteo_pressure",
            "valid_time": times[index] + "+08:00",
            "source_url": source_url,
        }
        for field, variable in PRESSURE_VARIABLES.items():
            series = hourly.get(variable)
            value = series[index] if series and index < len(series) else None
            result[field] = None if value is None else round(float(value), 1)
        return result
    except Exception as exc:  # provider 不抛异常出界
        return {"error": str(exc), "provider": "open_meteo_pressure"}
    finally:
        if own_client:
            await client.aclose()
