"""HTTP 路由：fact_pack / explain(SSE) / warnings / charts / healthz。

约定（与设计文档一致）：

- ``/api/fact_pack`` 是确定性的，不走 LLM；
- ``/api/explain`` 用 SSE 推进度与最终 JSON（单次 LLM 调用，不逐 token 转发，
  因为校验必须先看到完整 JSON，逐 token 推到前端等于把没校验过的内容展示出去）；
- 失败一律是结构化 JSON（``{"error": ...}``），不让前端猜。

``fact_pack`` 结果按「地名+天数」在进程内缓存 15 分钟（设计文档 §8），
键里带 schema 版本，避免升级后拿到旧结构。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from skylens import __version__
from skylens.core.explain import explain as explain_pack
from skylens.core.fact_pack import build_fact_pack
from skylens.providers.charts import fetch_charts
from skylens.settings import get_settings

router = APIRouter(prefix="/api")
SHANGHAI = ZoneInfo("Asia/Shanghai")

PACK_TTL_SECONDS = 900.0
_PACK_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def reset_pack_cache() -> None:
    """测试与「想要最新数据」时用。"""
    _PACK_CACHE.clear()


def _cache_key(place: str, days: int) -> str:
    return f"v1|{place.strip()}|{days}"


async def get_pack(place: str, days: int) -> dict[str, Any]:
    key = _cache_key(place, days)
    cached = _PACK_CACHE.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < PACK_TTL_SECONDS:
        return cached[1]
    pack = await build_fact_pack(place, days=days)
    if "error" not in pack:
        _PACK_CACHE[key] = (now, pack)
    return pack


def pack_error(pack: dict[str, Any]) -> HTTPException:
    code = pack.get("error")
    status = 404 if code == "geocode_not_found" else 400 if code == "missing_input" else 502
    return HTTPException(status_code=status, detail={"error": code, "detail": pack.get("detail")})


class ExplainRequest(BaseModel):
    place: str = Field(min_length=1)
    days: int = Field(default=7, ge=1, le=16)


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "time": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
    }


@router.get("/config")
async def config() -> dict[str, Any]:
    """前端需要的公开配置。

    天地图 key 是**浏览器端** key（服务端请求会被判 403「请使用浏览器访问」），必须下发到前端；
    它本来就会出现在网络请求里，不算机密，但只在本地 .env 维护一份。
    """
    settings = get_settings()
    return {
        "tianditu_key": settings.tianditu_key or None,
        "map_approval_no": settings.map_approval_no or None,
        "attribution": {"basemap": "天地图（已审图）", "clouds": "NASA GIBS"},
    }


@router.get("/fact_pack")
async def fact_pack(
    place: str = Query(min_length=1), days: int = Query(default=7, ge=1, le=16)
) -> dict[str, Any]:
    pack = await get_pack(place, days)
    if "error" in pack:
        raise pack_error(pack)
    return pack


@router.get("/charts")
async def charts() -> dict[str, Any]:
    result = await fetch_charts(settings=get_settings())
    if "error" in result:
        return {"charts": [], "error": result["error"]}
    return {"charts": result["charts"], "source_url": result.get("source_url")}


@router.get("/warnings")
async def warnings(lat: float, lon: float) -> dict[str, Any]:
    """官方预警。**当前未接入**：没有和风天气 key，宁可返回空也不编造。"""
    return {
        "warnings": [],
        "available": False,
        "reason": "未配置和风天气 key（预警接入待 M4 后续完成）",
        "requested": {"lat": lat, "lon": lon},
        "policy": "官方原文原样传播，不得改写、不得截断；AI 解读必须分栏显示",
    }


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _explain_stream(place: str, days: int, request: Request) -> AsyncIterator[str]:
    yield _sse("stage", {"stage": "fact_pack", "message": "组装事实包（不走 LLM）"})
    pack = await get_pack(place, days)
    if "error" in pack:
        yield _sse("error", {"error": pack.get("error"), "detail": pack.get("detail")})
        return
    yield _sse(
        "stage",
        {
            "stage": "fact_pack",
            "ok": True,
            "fact_pack_id": pack["fact_pack_id"],
            "location": {
                "name": pack["location"]["name"],
                "admin": pack["location"]["admin"],
                "lat": pack["location"]["lat"],
                "lon": pack["location"]["lon"],
            },
        },
    )

    if await request.is_disconnected():
        return

    yield _sse("stage", {"stage": "explain", "message": "单次 LLM 调用 + 引用校验"})
    answer = await explain_pack(pack, settings=get_settings())
    yield _sse(
        "answer",
        {
            "answer": answer,
            "fact_pack_id": pack["fact_pack_id"],
            "degraded": bool(answer.get("degraded")),
        },
    )
    yield _sse("done", {"degraded": bool(answer.get("degraded"))})


@router.post("/explain")
async def explain(request: Request, payload: ExplainRequest) -> StreamingResponse:
    """SSE：stage(fact_pack) → stage(explain) → answer → done。"""
    return StreamingResponse(
        _explain_stream(payload.place, payload.days, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/explain")
async def explain_json(
    place: str = Query(min_length=1), days: int = Query(default=7, ge=1, le=16)
) -> dict[str, Any]:
    """非流式入口：便于 curl / 测试 / 以后接手机端，语义与 SSE 的 answer 一致。"""
    pack = await get_pack(place, days)
    if "error" in pack:
        raise pack_error(pack)
    answer = await explain_pack(pack, settings=get_settings())
    return {
        "fact_pack_id": pack["fact_pack_id"],
        "answer": answer,
        "degraded": bool(answer.get("degraded")),
    }
