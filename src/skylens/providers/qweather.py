"""和风天气：官方预警（**原文完整搬运**）与中文地名。

合规红线（26 号令第九条）：预警的 ``text`` 必须原样引用，不得改写、截断、合并；
所以这里只做字段搬运与结构化，不加工文字。AI 的解读在解释层单独分栏输出。

实测要点（2026-11-15）：

- 新版控制台给每个账号分配独立 **API Host**（形如 ``xxx.re.qweatherapi.com``），
  继续用 ``devapi.qweather.com`` 会被判 403 ``Invalid Host``；
- 城市搜索路径是 ``/geo/v2/city/lookup``，预警是 ``/v7/warning/now``，都在同一个 host 下；
- 业务状态码在响应体 ``code`` 里（``200`` 成功、``204`` 无数据、``401/402/403`` 密钥/额度/权限）。
"""

from __future__ import annotations

from typing import Any

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

GEO_PATH = "/geo/v2/city/lookup"
WARNING_PATH = "/v7/warning/now"
PUBLIC_POLICY = "官方原文原样传播：不得改写、不得截断、不得合并"


def geo_url(settings: Settings) -> str:
    return f"{settings.qweather_base_url}{GEO_PATH}"


def warning_url(settings: Settings) -> str:
    return f"{settings.qweather_base_url}{WARNING_PATH}"


def parse_warnings(payload: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    """QWeather 预警 → fact_pack 的 warnings 数组。字段只搬运，不改写。"""
    warnings: list[dict[str, Any]] = []
    for item in payload.get("warning") or []:
        warnings.append(
            {
                "title": item.get("title"),
                "level": item.get("level"),
                "type": item.get("typeName"),
                "issuer": item.get("sender"),
                "issued_at": item.get("pubTime"),
                "start_time": item.get("startTime"),
                "end_time": item.get("endTime"),
                "status": item.get("status"),
                "text": item.get("text"),  # 原文，禁止任何加工
                "source_url": source_url,
                "policy": PUBLIC_POLICY,
            }
        )
    return warnings


def _code_error(payload: dict[str, Any]) -> str | None:
    code = str(payload.get("code", "")).strip()
    if code in ("200", "204"):
        return None
    if code == "401":
        return "401 无效的 API key"
    if code == "402":
        return "402 超过每日访问次数或余额不足"
    if code == "403":
        return "403 无访问权限（免费版可能不含预警接口）"
    return f"code={code or '空'}"


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

    url = warning_url(settings)
    params = {
        "location": f"{round(lon, 2)},{round(lat, 2)}",
        "key": settings.qweather_key.get_secret_value(),
        "lang": "zh",
    }
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
            payload = resp.json() if resp.content else {"code": "204"}
            cache_set(cache, key, payload)

        error = _code_error(payload)
        if error is not None:
            return {
                "provider": "qweather",
                "available": False,
                "warnings": [],
                "error": error,
                "source_url": source_url,
            }
        warnings = parse_warnings(payload, source_url)
        return {
            "provider": "qweather",
            "available": True,
            "warnings": warnings,
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
