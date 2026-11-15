"""METAR：最近机场的**真观测**（fact_pack ``observed`` 与 ``trend_24h`` 的来源）。

旧仓没有这一块。要点：

- 用 ``bbox`` 找附近站点（不维护机场静态表），最近一次实况优先；
- 单位一律换算成公制：JSON 里 ``wspd`` 是**节**、``visib`` 是**法定英里**、
  ``clouds[].base`` 是**英尺**、``altim`` 是 hPa——旧仓在请求参数里写死英制正是要清掉的债；
- 站点距离与海拔差必须落成 ``representativeness``，这是「小镇实况不准」的诚实来源。

实测（2026-11-15）：锡林浩特 ZBXH 当时无可用报，bbox 只能拿到呼和浩特 ZBHH（约 300 km），
正是设计文档里「观测代表性低」的真实场景。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.core import units
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_URL = registry.METAR_API

# 代表性阈值：距离 km / 海拔差 m
REPRESENTATIVENESS = ((50.0, 300.0, "高"), (150.0, 500.0, "中"))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def relative_humidity(temp_c: float, dewpoint_c: float) -> float:
    """由温度与露点反算相对湿度（Magnus/Tetens 公式，衍生量，需注明）。"""
    a, b = 17.625, 243.04
    exponent = a * dewpoint_c / (b + dewpoint_c) - a * temp_c / (b + temp_c)
    return round(100.0 * math.exp(exponent), 0)


def visibility_m(value: float | str | None) -> int | None:
    """``visib`` 在 METAR JSON 里是法定英里（可能是 ``"6+"`` 这类字符串）。"""
    if value is None:
        return None
    text = str(value).strip().rstrip("+")
    try:
        return round(units.mile_to_m(float(text)))
    except ValueError:
        return None


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def num(value: Any) -> float | None:
    """METAR 里 ``wdir`` 可能是 ``"VRB"``、``visib`` 可能是 ``"6+"``，一律不假设是数字。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().rstrip("+"))
    except ValueError:
        return None


def representativeness(distance_km: float, elevation_delta_m: float | None) -> dict[str, str]:
    delta = abs(elevation_delta_m) if elevation_delta_m is not None else 0.0
    level = "低"
    verdict = "不能代表当地局地实况"
    for max_km, max_delta, candidate in REPRESENTATIVENESS:
        if distance_km <= max_km and delta <= max_delta:
            level = candidate
            break
    if level == "高":
        verdict = "代表性较好"
    elif level == "中":
        verdict = "可作为参照但不代表局地"

    detail = f"{distance_km:.0f} km"
    if elevation_delta_m is not None:
        detail += f"、海拔差 {elevation_delta_m:+.0f} m"
    return {"level": level, "reason": f"{detail}，{verdict}"}


def _cloud_layer(cloud: dict[str, Any]) -> dict[str, Any]:
    base = num(cloud.get("base"))
    return {
        "cover": cloud.get("cover"),
        "base_m": None if base is None else round(units.ft_to_m(base)),
    }


def _knots_to_ms(value: Any) -> float | None:
    knots = num(value)
    return None if knots is None else round(units.knots_to_ms(knots), 1)


def _latest_by_station(reports: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        station = report.get("icaoId")
        if not station or report.get("temp") is None:
            continue
        grouped.setdefault(station, []).append(report)
    for station_reports in grouped.values():
        station_reports.sort(key=lambda r: r.get("reportTime") or "")
    return grouped


def _trend(history: list[dict[str, Any]], latest: dict[str, Any]) -> dict[str, Any]:
    """近 24h 变化：温度、气压、风向（取窗口内最早一条与前一条 3h 记录）。"""
    if not history:
        return {}
    latest_time = parse_time(latest["reportTime"])
    window_start = latest_time - timedelta(hours=24)
    in_window = [r for r in history if parse_time(r["reportTime"]) >= window_start]
    oldest = in_window[0] if in_window else history[0]

    trend: dict[str, Any] = {
        "basis": f"METAR {latest['icaoId']} 近 24h 序列（{len(in_window)} 条报）",
    }
    oldest_temp, latest_temp = num(oldest.get("temp")), num(latest.get("temp"))
    if oldest_temp is not None and latest_temp is not None:
        trend["temp_change_c"] = round(latest_temp - oldest_temp, 1)
    oldest_pressure, latest_pressure = num(oldest.get("altim")), num(latest.get("altim"))
    if oldest_pressure is not None and latest_pressure is not None:
        trend["pressure_change_hpa"] = round(latest_pressure - oldest_pressure, 1)
    oldest_dir, latest_dir = num(oldest.get("wdir")), num(latest.get("wdir"))
    if oldest_dir is not None and latest_dir is not None:
        trend["wind_dir_change_deg"] = round((latest_dir - oldest_dir + 180) % 360 - 180, 0)

    three_hours_ago = latest_time - timedelta(hours=3)
    candidates = [
        r
        for r in history
        if r is not latest
        and abs((parse_time(r["reportTime"]) - three_hours_ago).total_seconds()) <= 3600
    ] or [r for r in history if r is not latest and parse_time(r["reportTime"]) < latest_time]
    if candidates and latest_pressure is not None:
        previous_pressure = num(candidates[-1].get("altim"))
        if previous_pressure is not None:
            trend["pressure_trend_3h_hpa"] = round(latest_pressure - previous_pressure, 1)
    return trend


async def fetch_nearest(
    lat: float,
    lon: float,
    *,
    place: str = "",
    elevation_m: float | None = None,
    hours: int = 24,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """最近可用 METAR 站点的观测 + 24h 趋势。失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    own_client = client is None
    client = client or create_client(settings)
    try:
        reports: list[dict[str, Any]] = []
        used_url = ""
        for radius in (4.0, 8.0):
            params = {
                "bbox": registry.box_around(lat, lon, radius),
                "format": "json",
                "hours": hours,
            }
            used_url = str(httpx.Request("GET", SOURCE_URL, params=params).url)
            key = make_key(SOURCE_URL, params)
            payload = cache_get(cache, key, registry.TTLS.metar)
            if payload is None:
                resp = await client.get(SOURCE_URL, params=params)
                payload = resp.json() if resp.status_code == 200 and resp.content else []
                cache_set(cache, key, payload)
            if payload:
                reports = payload
                break

        if not reports:
            return {
                "provider": "metar",
                "available": False,
                "error": "附近 8° 内无可用 METAR 报",
                "source_url": used_url,
            }

        grouped = _latest_by_station(reports)
        if not grouped:
            return {"provider": "metar", "available": False, "error": "METAR 解析后无有效站点"}

        candidates: list[tuple[float, str, list[dict[str, Any]]]] = []
        for station_id, history in grouped.items():
            latest = history[-1]
            station_lat, station_lon = num(latest.get("lat")), num(latest.get("lon"))
            if station_lat is None or station_lon is None:
                continue
            candidates.append(
                (haversine_km(lat, lon, station_lat, station_lon), station_id, history)
            )
        if not candidates:
            return {"provider": "metar", "available": False, "error": "METAR 站点缺少坐标"}

        distance, station_id, history = min(candidates, key=lambda item: item[0])
        latest = history[-1]
        station_elev = num(latest.get("elev"))
        elevation_delta = (
            None
            if elevation_m is None or station_elev is None
            else station_elev - float(elevation_m)
        )

        valid_time = parse_time(latest["reportTime"])
        age_minutes = int((datetime.now(UTC) - valid_time).total_seconds() // 60)
        temp = num(latest["temp"])
        dewp = num(latest.get("dewp"))

        observed: dict[str, Any] = {
            "provider": "metar",
            "available": True,
            "station": {
                "id": station_id,
                "name": latest.get("name", station_id),
                "distance_km": round(distance),
                "elevation_m": None if station_elev is None else round(station_elev),
            },
            "valid_time": valid_time.astimezone(SHANGHAI).isoformat(timespec="seconds"),
            "age_minutes": age_minutes,
            "temp_c": temp,
            "dewpoint_c": dewp,
            "rh_pct": None if temp is None or dewp is None else relative_humidity(temp, dewp),
            "pressure_msl_hpa": num(latest.get("altim")),
            "wind_dir_deg": num(latest.get("wdir")),
            "wind_gust_ms": _knots_to_ms(latest.get("wgst")),
            "wind_speed_ms": _knots_to_ms(latest.get("wspd")),
            "cloud_layers": [_cloud_layer(cloud) for cloud in (latest.get("clouds") or [])],
            "visibility_m": visibility_m(latest.get("visib")),
            "weather_code": latest.get("wxString"),
            "raw": latest.get("rawOb"),
            "source": f"METAR {station_id}",
            "source_url": used_url,
            "representativeness": representativeness(distance, elevation_delta),
        }
        trend = _trend(history, latest)
        # 契约里 3h 变压属于观测块（trend_24h 只放 24h 变化）
        observed["pressure_trend_3h_hpa"] = trend.pop("pressure_trend_3h_hpa", None)
        observed["trend_24h"] = trend
        if place:
            rep = observed["representativeness"]
            rep["reason"] = (
                f"距{place}最近的可用站点是 {latest.get('name', station_id)}"
                f"（{station_id}），{rep['reason']}"
            )
        return observed
    except Exception as exc:  # provider 不抛异常出界
        return {"provider": "metar", "available": False, "error": str(exc)}
    finally:
        if own_client:
            await client.aclose()
