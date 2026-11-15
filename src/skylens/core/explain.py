"""解释层：**单次** LLM 调用，把 fact_pack 写成人话。

不做 agent 循环——便宜模型的 tool-calling 稳定性不足以支撑多轮自主取数，而取数路径本来就是确定的。
失败路径明确：JSON 不合法 / 缺字段 / 引用解析不了 → 带错误信息重试 1 次 → 仍失败走模板降级。

``degraded`` 字段标记本条是否来自模板（true 表示「本次未生成解释」）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from skylens.core import template, validate
from skylens.settings import Settings

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "explain_v1.txt"
SHANGHAI = ZoneInfo("Asia/Shanghai")

Completer = Callable[[list[dict[str, str]], Settings], Awaitable[str]]


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def data_times(pack: dict[str, Any]) -> str:
    observed = pack.get("observed") or {}
    synoptic = pack.get("synoptic") or {}
    parts = [
        f"观测 {observed.get('valid_time')}" if observed.get("valid_time") else "观测 缺",
        f"环流 {synoptic.get('valid_time')}" if synoptic.get("valid_time") else "环流 缺",
        f"fact_pack 生成于 {pack.get('generated_at')}",
    ]
    return "；".join(parts)


def compact_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """给 LLM 的精简事实包：删掉它用不上的长字段，降低输入 token 与截断风险。

    删的是：地理编码候选（前端用）、provider 耗时、天气图的 PNG 长 URL、
    METAR 原始报文的重复副本。保留所有**数值**与来源，解释层因此仍然可溯源。
    """
    observed = dict(pack.get("observed") or {})
    observed.pop("raw", None)

    synoptic = dict(pack.get("synoptic") or {})
    synoptic["charts"] = [
        {key: value for key, value in chart.items() if key != "url"}
        for chart in (synoptic.get("charts") or [])
    ]

    location = {
        key: value
        for key, value in (pack.get("location") or {}).items()
        if key != "geocode_candidates"
    }
    provenance = pack.get("provenance") or {}
    return {
        "schema_version": pack.get("schema_version"),
        "generated_at": pack.get("generated_at"),
        "location": location,
        "observed": observed,
        "trend_24h": pack.get("trend_24h"),
        "forecast": pack.get("forecast"),
        "synoptic": synoptic,
        "climate": pack.get("climate"),
        "warnings": pack.get("warnings") or [],
        "provenance": {"missing": provenance.get("missing"), "notes": provenance.get("notes")},
    }


def build_messages(pack: dict[str, Any]) -> list[dict[str, str]]:
    import json

    system = (
        load_prompt()
        .replace("__NOW__", datetime.now(SHANGHAI).isoformat(timespec="minutes"))
        .replace("__DATA_TIMES__", data_times(pack))
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(compact_pack(pack), ensure_ascii=False)},
    ]


async def call_llm(messages: list[dict[str, str]], settings: Settings) -> str:
    """默认 completer：OpenAI 兼容接口，JSON 输出模式。"""
    from openai import AsyncOpenAI

    from skylens.net import create_client

    http_client = create_client(settings)
    client = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.require_llm_key(),
        timeout=settings.http_timeout_s * 3,
        max_retries=0,
        http_client=http_client,
    )
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            response_format={"type": "json_object"},
            messages=messages,  # type: ignore[arg-type]
        )
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("输出被截断（finish_reason=length），请精简后重试")
        return choice.message.content or ""
    finally:
        await client.close()


def _parse_json(raw: str) -> dict[str, Any]:
    import json

    text = raw.strip()
    if text.startswith("```"):  # 模型偶尔无视「不要 markdown」
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _problems(answer: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    problems = [f"缺少字段 {key}" for key in validate.missing_keys(answer)]
    problems.extend(f"引用无法解析：{ref}" for ref in validate.unresolved_refs(answer, pack))
    return problems


async def explain(
    pack: dict[str, Any],
    *,
    settings: Settings | None = None,
    completer: Completer | None = None,
    attempts: int = 2,
) -> dict[str, Any]:
    """返回解释 JSON；失败一律降级为模板版本（``degraded: true``），不抛异常。"""
    settings = settings or Settings()
    completer = completer or call_llm
    messages = build_messages(pack)
    last_problems: list[str] = []

    for attempt in range(attempts):
        try:
            raw = await completer(messages, settings)
            answer = _parse_json(raw)
        except Exception as exc:  # 网络/截断/解析失败都算一次失败尝试
            last_problems = [f"{type(exc).__name__}: {exc}"]
        else:
            problems = _problems(answer, pack)
            if not problems:
                answer["degraded"] = False
                return answer
            last_problems = problems

        if attempt + 1 < attempts:
            # 不回灌上一次的全文（可能已被截断），只给问题清单，避免上下文继续膨胀
            messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过校验："
                        + "；".join(last_problems)
                        + "。请直接输出精简且合法的完整 JSON，facts 不超过 6 条。"
                    ),
                },
            ]

    fallback = template.render(pack)
    fallback["degraded"] = True
    fallback["fallback_reason"] = "；".join(last_problems)[:300]
    return fallback
