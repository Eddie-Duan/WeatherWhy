"""解释层测试：正常路径、引用不合法、JSON 非法、完全失败——全部不许抛异常。"""

from __future__ import annotations

import json
from typing import Any

from skylens.core import explain, validate
from skylens.settings import Settings

SETTINGS = Settings(_env_file=None)


def answer_json(*, bad_ref: bool = False) -> str:
    ref = "observed.temp_c_2m" if bad_ref else "observed.temp_c"
    return json.dumps(
        {
            "headline": "冷高压后部晴冷，夜间辐射降温强",
            "facts": [
                {"label": "现在气温", "value": "10 °C", "ref": ref},
                {"label": "500hPa 高度", "value": "5503 m", "ref": "synoptic.h500_geopotential_m"},
            ],
            "observed": "观测取自 ZBAA，压力 1025 hPa。",
            "forecast": "四模式最高气温 -1.6 °C，离散度 1.4 °C。",
            "inference": {
                "text": "平直西风下冷空气缓慢东移，最不确定的是云量。",
                "confidence": "中",
                "basis": ["synoptic.h500_geopotential_m"],
            },
            "uncertainty": "云量分歧最大。",
            "advice": "注意夜间降温。",
            "not_covered": ["官方预警（需和风天气 key）"],
            "citations": ["https://example.invalid/metar"],
        },
        ensure_ascii=False,
    )


class TestExplainSuccess:
    async def test_valid_answer_passes_validation(self, sample_pack: dict) -> None:
        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            return answer_json()

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert answer["degraded"] is False
        assert answer["headline"].startswith("冷高压")
        validate.assert_refs_resolvable(answer, sample_pack)

    async def test_prompt_carries_now_and_data_times(self, sample_pack: dict) -> None:
        captured: list[list[dict[str, str]]] = []

        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            captured.append(messages)
            return answer_json()

        await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        system = captured[0][0]["content"]
        assert "当前时刻：" in system
        assert "2026-11-15T17:00:00+08:00" in system  # 观测有效时刻进了数据时刻
        assert "我们是天气预报" not in system
        assert "禁止推测或补全" in system


class TestExplainDegrades:
    async def test_bad_ref_is_retried_then_degrades(self, sample_pack: dict) -> None:
        calls: list[list[dict[str, str]]] = []

        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            calls.append(messages)
            return answer_json(bad_ref=True)

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert len(calls) == 2, "应重试一次"
        assert len(calls[1]) == 3, "重试带上一条问题说明（不回灌可能被截断的全文）"
        assert "引用无法解析" in calls[1][-1]["content"]
        assert answer["degraded"] is True
        assert "引用无法解析" in answer["fallback_reason"]

    async def test_retry_can_succeed(self, sample_pack: dict) -> None:
        calls: list[int] = []

        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            calls.append(1)
            return answer_json(bad_ref=len(calls) == 1)

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert answer["degraded"] is False
        assert len(calls) == 2

    async def test_invalid_json_degrades_without_crash(self, sample_pack: dict) -> None:
        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            return "这不是 JSON"

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert answer["degraded"] is True
        assert "JSONDecodeError" in answer["fallback_reason"]

    async def test_network_failure_degrades(self, sample_pack: dict) -> None:
        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            raise TimeoutError("upstream timeout")

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert answer["degraded"] is True
        assert "TimeoutError" in answer["fallback_reason"]
        validate.assert_refs_resolvable(answer, sample_pack)

    async def test_missing_fields_degrade(self, sample_pack: dict) -> None:
        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            return json.dumps({"headline": "只有一句话"})

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)

        assert answer["degraded"] is True
        assert "缺少字段" in answer["fallback_reason"]

    async def test_markdown_fenced_json_is_tolerated(self, sample_pack: dict) -> None:
        async def completer(messages: list[dict[str, str]], settings: Any) -> str:
            return "```json\n" + answer_json() + "\n```"

        answer = await explain.explain(sample_pack, settings=SETTINGS, completer=completer)
        assert answer["degraded"] is False
