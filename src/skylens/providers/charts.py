"""天气图：JMA 地面图（可直链 PNG）+ 中央气象台公开产品（外链页面）。

只做**链接与元数据**，不缓存图片（尊重源的 ToS，见设计文档 §11）。
JMA 的 ``list.json`` 里 ``asia`` 组覆盖亚洲地面天气图，``near`` 组是日本周边；
两组都提供 ``now``（实况序列）与 ``ft24`` / ``ft48``（予想）。
文件名里带有效时刻：``..._20261115090000_MET...`` → UTC，转 Asia/Shanghai 展示。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from skylens.cache.store import TTLCache, cache_get, cache_set, make_key
from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings

JMA_LIST_URL = "https://www.jma.go.jp/bosai/weather_map/data/list.json"
JMA_PNG_BASE = "https://www.jma.go.jp/bosai/weather_map/data/png/"
JMA_LICENSE = "JMA 政府標準利用規約（転載時は出典明記）"
NMC_LICENSE = "中央气象台公开产品（注明来源并外链）"

NMC_PAGES: tuple[tuple[str, str], ...] = (
    (
        "中央气象台 地面天气图",
        "http://www.nmc.cn/publish/observations/china/dm/weatherchart-dm.htm",
    ),
    (
        "中央气象台 500hPa 高度场",
        "http://www.nmc.cn/publish/observations/china/dm/weatherchart-h500.htm",
    ),
    (
        "中央气象台 850hPa 高度场",
        "http://www.nmc.cn/publish/observations/china/dm/weatherchart-h850.htm",
    ),
)

TIME_PATTERN = re.compile(r"_(\d{14})_")
GROUP_ORDER = ("asia", "near")
SLOT_TITLES = (("now", "实况"), ("ft24", "24 小时予想"), ("ft48", "48 小时予想"))


def filename_time(filename: str) -> datetime | None:
    match = TIME_PATTERN.search(filename)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def to_shanghai(moment: datetime) -> str:
    return moment.astimezone(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def build_charts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从 JMA 的 list.json 里挑出「亚洲实况 + 24/48h 予想」，再补中央气象台外链。"""
    charts: list[dict[str, Any]] = []
    group = next((payload[name] for name in GROUP_ORDER if payload.get(name)), None)
    if not group:
        return charts

    for slot, slot_title in SLOT_TITLES:
        filenames = group.get(slot) or []
        if not filenames:
            continue
        latest = max(filenames, key=lambda name: filename_time(name) or datetime.min)
        moment = filename_time(latest)
        charts.append(
            {
                "title": f"JMA 亚洲地面天气图（{slot_title}）",
                "url": JMA_PNG_BASE + latest,
                "valid_time": to_shanghai(moment) if moment else None,
                "license": JMA_LICENSE,
                "kind": "地面天气图" if slot == "now" else "预报天气图",
            }
        )

    for title, url in NMC_PAGES:
        charts.append(
            {
                "title": title,
                "url": url,
                "valid_time": None,
                "license": NMC_LICENSE,
                "kind": "高空/地面天气图",
            }
        )
    return charts


async def fetch_charts(
    *,
    settings: Settings | None = None,
    cache: TTLCache | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """天气图链接列表。失败返回 ``{"error": ...}``，不抛异常。"""
    settings = settings or Settings()
    own_client = client is None
    client = client or create_client(settings)
    try:
        key = make_key(JMA_LIST_URL)
        payload = cache_get(cache, key, registry.TTLS.charts)
        if payload is None:
            resp = await client.get(JMA_LIST_URL)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "provider": "charts"}
            payload = resp.json()
            cache_set(cache, key, payload)

        charts = build_charts(payload)
        if not charts:
            return {"error": "list.json 中无可用天气图", "provider": "charts"}
        return {"provider": "charts", "charts": charts, "source_url": JMA_LIST_URL}
    except Exception as exc:  # provider 不抛异常出界
        return {"error": str(exc), "provider": "charts"}
    finally:
        if own_client:
            await client.aclose()
