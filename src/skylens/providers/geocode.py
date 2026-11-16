"""中文地名优先的地理编码：Nominatim → 和风天气 GeoAPI → Open-Meteo → 本地兜底表。

**实测结论（2026-11-16，三家都拿真实请求验过）**：

- Open-Meteo geocoding 对「明安图镇」「正镶白旗」这类旗县级中文地名**返回空**；
- 和风 GeoAPI 的城市库只到县级：``明安图镇`` 会被匹配成**吉林安图**（43.11, 128.90），
  但 ``正镶白旗``、``锡林浩特`` 这类县级/市级名称很准；
- Nominatim 能精确命中镇级：``明安图镇 → 42.2984, 115.0014（正镶白旗/锡郭勒盟/内蒙古）``，
  但它会超时/限流——实测今天整条链路因为它 ConnectTimeout 而全部失败。

因此这里做三件防护：

1. **逐个源独立 try**：Nominatim 超时不再拖死整条链，自动降级到下一个源；
2. **中文行政区名做合理性过滤**：查询去掉「镇/市/旗/县/区/苏木/乡」后的核心词必须出现在候选名里，
   否则丢弃（这就是「明安图镇 → 吉林安图」被挡掉的地方）；
3. **本地兜底表**：本项目先做透的 1–3 个地点有坐标常量，网络地理编码全挂时仍可用，
   结果标成 ``local_table``、置信度 0.7，并在返回里注明「网络地理编码不可用」。

所有候选都返回（``limit`` 5），不做「只取第一条」的静默猜测。
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
_ADMIN_SUFFIXES = "镇市旗县区苏木乡"

# 本项目先做透的 1–3 个地点：网络地理编码全部不可用时的兜底。
# 坐标来自地理编码/官方资料核对，置信度故意只给 0.7。
LOCAL_PLACES: dict[str, dict[str, Any]] = {
    "明安图镇": {
        "name": "明安图镇",
        "admin": "内蒙古自治区 正镶白旗",
        "lat": 42.2984,
        "lon": 115.0014,
        "elevation_m": 1345.0,
    },
    "明安图": {
        "name": "明安图镇",
        "admin": "内蒙古自治区 正镶白旗",
        "lat": 42.2984,
        "lon": 115.0014,
        "elevation_m": 1345.0,
    },
    "正镶白旗": {
        "name": "正镶白旗",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 42.5323,
        "lon": 114.9925,
        "elevation_m": 1350.0,
    },
    "锡林浩特": {
        "name": "锡林浩特市",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 43.9443,
        "lon": 116.0919,
        "elevation_m": 1010.0,
    },
    "锡林浩特市": {
        "name": "锡林浩特市",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 43.9443,
        "lon": 116.0919,
        "elevation_m": 1010.0,
    },
    "二连浩特": {
        "name": "二连浩特市",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 43.6524,
        "lon": 111.9775,
        "elevation_m": 966.0,
    },
    "二连浩特市": {
        "name": "二连浩特市",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 43.6524,
        "lon": 111.9775,
        "elevation_m": 966.0,
    },
    "二连": {
        "name": "二连浩特市",
        "admin": "内蒙古自治区 锡林郭勒盟",
        "lat": 43.6524,
        "lon": 111.9775,
        "elevation_m": 966.0,
    },
}


def _has_cjk(text: str) -> bool:
    return any(_CJK[0] <= ch <= _CJK[1] for ch in text)


def _core_name(query: str) -> str:
    """去掉行政区后缀：「明安图镇」→「明安图」，「锡林浩特市」→「锡林浩特」。"""
    core = query.strip()
    while len(core) > 2 and core[-1] in _ADMIN_SUFFIXES:
        core = core[:-1]
    return core


def _plausible(query: str, name: str) -> bool:
    """中文行政区查询的核心词必须出现在候选名里，否则视为误匹配。

    这条规则专门挡住「明安图镇 → 吉林安图」：核心词「明安图」不在「安图」里。
    非中文查询不做这项检查（英文地名靠相似度就够了）。
    """
    if not _has_cjk(query) or not _has_cjk(name):
        return True
    core = _core_name(query)
    # 只要求「核心词出现在候选名里」：允许 明安图→明安图镇、锡林浩特→锡林浩特市，
    # 但挡掉 明安图镇→安图（「安图」虽然是子串，核心词「明安图」不在候选里）。
    return len(core) < 2 or core in name


def _score(query: str, name: str, rank: int, base: float) -> float:
    similarity = difflib.SequenceMatcher(None, query, name).ratio()
    return round(min(0.99, base * (0.6 + 0.4 * similarity) * (1.0 - 0.08 * rank)), 2)


def _candidate(
    name: str, admin: str, lat: float, lon: float, elevation: float | None, score: float
) -> dict[str, Any]:
    return {
        "name": name,
        "admin": admin,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "elevation_m": elevation,
        "score": score,
    }


def _from_qweather(payload: Mapping, query: str) -> list[dict[str, Any]]:
    out = []
    for rank, item in enumerate((payload.get("location") or [])[:5]):
        name = item.get("name") or query
        if not _plausible(query, name):
            continue
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
        if not _plausible(query, name):
            continue
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
    base = 0.6 if _has_cjk(query) else 0.8
    out = []
    for rank, item in enumerate(results[:5]):
        name = item.get("name") or query
        if not _plausible(query, name):
            continue
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


def _from_local(query: str) -> list[dict[str, Any]]:
    hit = LOCAL_PLACES.get(query.strip())
    if hit is None:
        return []
    return [
        _candidate(
            name=hit["name"],
            admin=hit["admin"],
            lat=hit["lat"],
            lon=hit["lon"],
            elevation=hit["elevation_m"],
            score=0.7,
        )
    ]


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    cache: TTLCache | None,
    ttl: int,
    cache_key_params: dict[str, Any] | None = None,
    default: Any,
) -> Any:
    """带缓存的 GET：**只在 200 时缓存**，失败不污染 30 天的地理编码缓存。"""
    key = make_key(url, cache_key_params or params)
    cached = cache_get(cache, key, ttl)
    if cached is not None:
        return cached
    resp = await client.get(url, params=params)
    if resp.status_code != 200:
        raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
    payload = resp.json()
    cache_set(cache, key, payload)
    return payload if payload is not None else default


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
    attempts: list[dict[str, str]] = []

    async def run(source: str, factory) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        try:
            return await factory()
        except Exception as exc:  # 单个源失败只记账，不拖死整条链
            attempts.append({"source": source, "error": f"{type(exc).__name__}: {exc}".strip(": ")})
            return []

    try:
        candidates: list[dict[str, Any]] = []
        source = ""

        async def nominatim() -> list[dict[str, Any]]:
            params = {
                "q": query,
                "format": "jsonv2",
                "limit": 5,
                "accept-language": "zh",
                "addressdetails": 1,
            }
            payload = await _fetch_json(
                client,
                registry.NOMINATIM_SEARCH,
                params,
                cache=cache,
                ttl=registry.TTLS.geocode,
                default=[],
            )
            return _from_nominatim(payload, query)

        candidates = await run("nominatim", nominatim)
        if candidates:
            source = "nominatim"

        async def qweather_geo() -> list[dict[str, Any]]:
            if settings.qweather_key is None:
                return []
            url = qweather.geo_url(settings)
            params = {
                "location": query,
                "key": settings.qweather_key.get_secret_value(),
                "lang": "zh",
                "number": 5,
            }
            payload = await _fetch_json(
                client,
                url,
                params,
                cache=cache,
                ttl=registry.TTLS.geocode,
                cache_key_params={**params, "key": "<redacted>"},
                default={},
            )
            return _from_qweather(payload, query)

        if not candidates:
            candidates = await run("qweather", qweather_geo)
            if candidates:
                source = "qweather"

        async def open_meteo() -> list[dict[str, Any]]:
            params = {"name": query, "count": 5, "language": "zh", "format": "json"}
            payload = await _fetch_json(
                client,
                registry.OPEN_METEO_GEOCODING,
                params,
                cache=cache,
                ttl=registry.TTLS.geocode,
                default={},
            )
            return _from_open_meteo(payload, query)

        if not candidates:
            candidates = await run("open_meteo", open_meteo)
            if candidates:
                source = "open_meteo"

        if not candidates:
            candidates = _from_local(query)
            if candidates:
                source = "local_table"

        if not candidates:
            error: dict[str, Any] = {"error": "geocode_not_found", "query": query}
            if attempts:
                error["attempts"] = attempts
            return error

        best = max(candidates, key=lambda c: c["score"])
        location: dict[str, Any] = {
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
        if attempts:
            location["geocode_attempt_errors"] = attempts
        if source == "local_table":
            location["geocode_note"] = "网络地理编码不可用，已使用本地兜底表（置信度 0.7）"
        return location
    except Exception as exc:  # 最外层兜底，仍然不抛
        return {
            "error": "geocode_failed",
            "query": query,
            "detail": f"{type(exc).__name__}: {exc}".strip(": "),
            "attempts": attempts,
        }
    finally:
        if own_client:
            await client.aclose()
