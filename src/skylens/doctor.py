"""``skylens doctor``：一次把「环境、密钥、LLM、各数据源」都验一遍。

用于把「配好没有」这件事从口头确认变成可复跑的命令；每一行都带耗时与真实失败原因。
密钥只显示长度与前后各 2–3 个字符，绝不回显全文。
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from skylens.net import create_client
from skylens.providers import registry
from skylens.settings import Settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    latency_ms: int = 0
    critical: bool = False


def mask_secret(value: str | None) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return f"已配置（{len(value)} 字符）"
    return f"已配置（{len(value)} 字符，{value[:3]}…{value[-2:]}）"


async def _timed_check(name: str, coro: Any, *, critical: bool = False) -> Check:
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout=20)
        return Check(name, True, str(detail), int((time.perf_counter() - started) * 1000), critical)
    except Exception as exc:
        return Check(
            name,
            False,
            f"{type(exc).__name__}: {exc}"[:200],
            int((time.perf_counter() - started) * 1000),
            critical,
        )


async def _check_llm(settings: Settings) -> str:
    from openai import AsyncOpenAI

    http_client = create_client(settings)
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.require_llm_key(),
        timeout=settings.http_timeout_s,
        max_retries=0,
        http_client=http_client,
    )
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "回复 OK"}],
            max_tokens=4,
            temperature=0,
        )
        usage = response.usage
        return (
            f"{response.model}｜{usage.prompt_tokens}/{usage.completion_tokens} tokens"
            if usage
            else str(response.model)
        )
    finally:
        await client.close()


async def _check_open_meteo(client: httpx.AsyncClient) -> str:
    response = await client.get(
        registry.OPEN_METEO_FORECAST,
        params={
            "latitude": 42.3,
            "longitude": 115.0,
            "current": "temperature_2m",
            "forecast_days": 1,
            "timezone": "Asia/Shanghai",
        },
    )
    response.raise_for_status()
    current = response.json().get("current") or {}
    return f"current.temperature_2m={current.get('temperature_2m')} °C"


async def _check_metar(client: httpx.AsyncClient) -> str:
    response = await client.get(
        registry.METAR_API,
        params={"bbox": registry.box_around(42.3, 115.0, 8.0), "format": "json", "hours": 2},
    )
    if response.status_code == 204:
        return "204 附近无报（属正常降级路径）"
    response.raise_for_status()
    reports = response.json()
    stations = {report.get("icaoId") for report in reports}
    return f"{len(reports)} 条报，{len(stations)} 个站点"


async def _check_jma(client: httpx.AsyncClient) -> str:
    response = await client.get("https://www.jma.go.jp/bosai/weather_map/data/list.json")
    response.raise_for_status()
    payload = response.json()
    return f"list.json 分组 {', '.join(payload)}"


async def _check_oni(client: httpx.AsyncClient) -> str:
    response = await client.get("https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt")
    response.raise_for_status()
    return f"{len(response.text.splitlines())} 行 ONI 表"


async def _check_qweather(settings: Settings) -> str:
    """和风天气：没有 key 就报「未配置」，有 key 但 Host 不对会明确报 Invalid Host。"""
    from skylens.providers.qweather import fetch_warnings

    if settings.qweather_key is None:
        raise RuntimeError("未配置 SKYLENS_QWEATHER_KEY")
    result = await fetch_warnings(42.3, 115.0, settings=settings)
    if result.get("available"):
        return f"{len(result.get('warnings') or [])} 条生效预警｜{settings.qweather_api_host}"
    raise RuntimeError(str(result.get("error") or result.get("reason") or "不可用"))


async def run_checks(settings: Settings | None = None, *, check_llm: bool = True) -> list[Check]:
    settings = settings or Settings()
    client = create_client(settings)
    checks: list[Check] = []

    python_ok = sys.version_info >= (3, 12)
    checks.append(
        Check(
            "Python",
            python_ok,
            f"{sys.version.split()[0]}（需 ≥ 3.12）",
            critical=True,
        )
    )

    key = settings.llm_api_key_value
    checks.append(
        Check(
            "LLM 配置",
            key is not None,
            f"{settings.llm_provider}｜{settings.llm_base_url}｜"
            f"{settings.llm_model}｜key {mask_secret(key)}",
            critical=True,
        )
    )

    try:
        probe = settings.ensure_cache_dir() / ".doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("缓存目录", True, str(settings.cache_dir)))
    except Exception as exc:
        checks.append(Check("缓存目录", False, str(exc)[:200], critical=True))

    if check_llm:
        if key is None:
            checks.append(Check("LLM 连通", False, "缺少 SKYLENS_LLM_API_KEY，跳过", critical=True))
        else:
            checks.append(await _timed_check("LLM 连通", _check_llm(settings), critical=True))

    checks.append(await _timed_check("Open-Meteo", _check_open_meteo(client)))
    checks.append(await _timed_check("METAR", _check_metar(client)))
    checks.append(await _timed_check("和风天气", _check_qweather(settings)))
    checks.append(await _timed_check("JMA 天气图", _check_jma(client)))
    checks.append(await _timed_check("NOAA ONI", _check_oni(client)))
    await client.aclose()
    return checks


def all_critical_ok(checks: list[Check]) -> bool:
    return all(check.ok for check in checks if check.critical)
