"""和风天气：官方预警（**原文完整搬运**）。

合规红线（26 号令第九条）：预警原文必须原样引用，不得改写、截断、合并；
这里只做字段搬运与结构化，不加工文字。AI 的解读在解释层单独分栏输出。

实测要点（2026-11-15）：

- 新版控制台给每个账号独立 **API Host**（形如 ``xxx.re.qweatherapi.com``），
  旧的 ``devapi.qweather.com`` / ``api.qweather.com`` 会被判 403 ``Invalid Host``；
- 旧版 ``/v7/warning/now`` 已废弃（实测返回 403 ``Deprecated``，官方说明 2026-09 停用），
  新接口是 ``GET /weatheralert/v1/current/{lat}/{lon}``，仍是 ``?key=`` 鉴权（Bearer 会 401）；
- 响应带 ``metadata.attributions``（「国家预警信息发布中心」），按条款必须与数据共同展示。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

GEO_PATH = "/geo/v2/city/lookup"
ALERT_PATH = "/weatheralert/v1/current"
CURRENT_PATH = "/weather/v1/current"
PUBLIC_POLICY = "官方原文原样传播：不得改写、不得截断、不得合并"
SHANGHAI = ZoneInfo("Asia/Shanghai")

# 预警颜色 → 中文等级（unflagged 的取原名）
LEVEL_LABELS = {
    "white": "白色",
    "gray": "灰色",
    "green": "绿色",
    "blue": "蓝色",
    "yellow": "黄色",
    "amber": "琥珀色",
    "orange": "橙色",
    "red": "红色",
    "purple": "紫色",
    "black": "黑色",
}


def geo_url(settings: Settings) -> str:
    return f"{settings.qweather_base_url}{GEO_PATH}"


def current_url(settings: Settings, lat: float, lon: float) -> str:
    """本地格点实况：把坐标放进路径（最多两位小数）。"""
    return f"{settings.qweather_base_url}{CURRENT_PATH}/{lat:.2f}/{lon:.2f}"


def alert_url(settings: Settings, lat: float, lon: float) -> str:
    """新预警接口把坐标放进路径（最多两位小数）。"""
    return f"{settings.qweather_base_url}{ALERT_PATH}/{lat:.2f}/{lon:.2f}"


# 兼容旧名字：早期代码里叫 warning_url
warning_url = alert_url


def to_shanghai(value: str | None) -> str | None:
    """QWeather 预警时间给的是 UTC（``...Z``），统一转成 +08:00 再进 fact_pack。"""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(SHANGHAI).isoformat(timespec="seconds")


def parse_alerts(payload: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    """``alerts`` → fact_pack 的 warnings 数组。``description`` 一字不改。"""
    attributions = (payload.get("metadata") or {}).get("attributions") or []
    attribution = attributions[0] if attributions else None
    warnings: list[dict[str, Any]] = []
    for item in payload.get("alerts") or []:
        color = (item.get("color") or {}).get("code")
        warnings.append(
            {
                "title": item.get("headline"),
                "level": LEVEL_LABELS.get(str(color), color),
                "type": (item.get("eventType") or {}).get("name"),
                "issuer": item.get("senderName"),
                "issued_at": to_shanghai(item.get("issuedTime")),
                "start_time": to_shanghai(item.get("effectiveTime")),
                "end_time": to_shanghai(item.get("expireTime")),
                "status": (item.get("messageType") or {}).get("code"),
                "text": item.get("description"),  # 原文，禁止任何加工
                "advice": item.get("instruction"),
                "attribution": attribution,
                "source_url": source_url,
                "policy": PUBLIC_POLICY,
            }
        )
    return warnings


async def fetch_warnings(
    lat: float,
    lon: float,
    *,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """按坐标取官方预警。未配置 key 或接口无权限时如实返回不可用，不编造。"""
    settings = settings or Settings()
    if settings.qweather_key is None:
        return {
            "provider": "qweather",
            "available": False,
            "warnings": [],
            "reason": "未配置 SKYLENS_QWEATHER_KEY",
        }

    url = alert_url(settings, lat, lon)
    params = {"key": settings.qweather_key.get_secret_value(), "lang": "zh"}
    source_url = str(httpx.Request("GET", url, params={**params, "key": "<redacted>"}).url)

    own_client = client is None
    client = client or create_client(settings)
    try:
        key = make_key(url, {**params, "key": "<redacted>"})
        payload = cache_get(cache, key, registry.TTLS.metar)
        if payload is None:
            resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = str((resp.json().get("error") or {}).get("title", ""))
                except Exception:
                    detail = ""
                return {
                    "provider": "qweather",
                    "available": False,
                    "warnings": [],
                    "error": f"HTTP {resp.status_code} {detail}".strip(),
                    "source_url": source_url,
                }
            payload = resp.json() if resp.content else {}
            cache_set(cache, key, payload)

        warnings = parse_alerts(payload, source_url)
        return {
            "provider": "qweather",
            "available": True,
            "warnings": warnings,
            "attribution": (payload.get("metadata") or {}).get("attributions") or [],
            "source_url": source_url,
            "policy": PUBLIC_POLICY,
        }
    except Exception as exc:  # provider 不抛异常出界
        return {
            "provider": "qweather",
            "available": False,
            "warnings": [],
            "error": str(exc),
            "source_url": source_url,
        }
    finally:
        if own_client:
            await client.aclose()


def _value(block: dict[str, Any] | None) -> float | None:
    if not isinstance(block, dict):
        return None
    raw = block.get("value")
    try:
        return None if raw is None else float(raw)
    except (TypeError, ValueError):
        return None


def parse_current(payload: dict[str, Any], source_url: str) -> dict[str, Any]:
    """和风 ``/weather/v1/current`` → fact_pack 的 ``observed.local``。

    这是**格点/融合实况**，不是机场站点观测：它就在目标坐标上，能代表本地，
    但不是仪器直读记录——所以 ``kind`` 字段必须写清楚，前端与解释层都要区分。
    """
    humidity = payload.get("humidity")
    if isinstance(humidity, (int, float)) and humidity <= 1:
        humidity = humidity * 100
    cloud = payload.get("cloudCover")
    if isinstance(cloud, (int, float)) and cloud <= 1:
        cloud = cloud * 100
    condition = payload.get("condition") or {}
    wind = payload.get("wind") or {}
    precipitation = payload.get("precipitation") or {}
    amount = precipitation.get("amount") or {}
    return {
        "kind": "格点实况（非站点观测）",
        "valid_time": to_shanghai(payload.get("validTime")),
        "temp_c": _value(payload.get("temperature")),
        "feels_like_c": _value(payload.get("feelsLike")),
        "dewpoint_c": _value(payload.get("dewPoint")),
        "rh_pct": None if humidity is None else round(float(humidity)),
        "pressure_msl_hpa": _value(payload.get("pressure")),
        "wind_dir_deg": (wind.get("direction") or {}).get("degree"),
        "wind_speed_ms": _value(wind.get("speed")),
        "wind_gust_ms": _value(payload.get("windGust")),
        "visibility_m": _value(payload.get("visibility")),
        "cloud_cover_pct": None if cloud is None else round(float(cloud)),
        "precip_mm": _value(amount),
        "precip_type": precipitation.get("type"),
        "weather_text": condition.get("text"),
        "weather_code": condition.get("code"),
        "attribution": (payload.get("metadata") or {}).get("attributions") or [],
        "source": "和风天气 current（格点实况）",
        "source_url": source_url,
    }


async def fetch_now(
    lat: float,
    lon: float,
    *,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """本地格点实况。未配置 key 时返回 ``{"available": False, "reason": ...}``。"""
    settings = settings or Settings()
    if settings.qweather_key is None:
        return {
            "provider": "qweather_current",
            "available": False,
            "reason": "未配置 SKYLENS_QWEATHER_KEY",
        }

    url = current_url(settings, lat, lon)
    params = {"key": settings.qweather_key.get_secret_value(), "lang": "zh"}
    source_url = str(httpx.Request("GET", url, params={**params, "key": "<redacted>"}).url)

    own_client = client is None
    client = client or create_client(settings)
    try:
        key = make_key(url, {**params, "key": "<redacted>"})
        payload = cache_get(cache, key, registry.TTLS.metar)
        if payload is None:
            resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                return {
                    "provider": "qweather_current",
                    "available": False,
                    "error": f"HTTP {resp.status_code}",
                    "source_url": source_url,
                }
            payload = resp.json() if resp.content else {}
            cache_set(cache, key, payload)
        if not payload.get("temperature"):
            return {
                "provider": "qweather_current",
                "available": False,
                "error": "响应缺少 temperature",
                "source_url": source_url,
            }
        return {
            "provider": "qweather_current",
            "available": True,
            **parse_current(payload, source_url),
        }
    except Exception as exc:  # provider 不抛异常出界
        return {
            "provider": "qweather_current",
            "available": False,
            "error": str(exc),
            "source_url": source_url,
        }
    finally:
        if own_client:
            await client.aclose()
