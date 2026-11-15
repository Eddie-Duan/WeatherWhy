"""和风天气预警测试：字段原样搬运、业务状态码处理、无 key 时不编造。"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import qweather
from skylens.settings import Settings

SETTINGS = Settings(_env_file=None, qweather_key="k", qweather_api_host="demo.re.qweatherapi.com")

WARNING_PAYLOAD = {
    "code": "200",
    "updateTime": "2026-11-15T11:10+08:00",
    "warning": [
        {
            "id": "101",
            "sender": "正镶白旗气象台",
            "pubTime": "2026-11-15T11:00+08:00",
            "title": "大风蓝色预警信号",
            "startTime": "2026-11-15T11:00+08:00",
            "endTime": "2026-11-16T11:00+08:00",
            "status": "active",
            "level": "蓝色",
            "typeName": "大风",
            "text": (
                "正镶白旗气象台2026年11月15日11时00分发布大风蓝色预警信号：24小时内可能受大风影响。"
            ),
        }
    ],
}


class TestUrls:
    def test_urls_use_configured_host(self) -> None:
        assert qweather.geo_url(SETTINGS) == "https://demo.re.qweatherapi.com/geo/v2/city/lookup"
        assert qweather.warning_url(SETTINGS) == "https://demo.re.qweatherapi.com/v7/warning/now"

    def test_scheme_can_be_given_explicitly(self) -> None:
        settings = Settings(_env_file=None, qweather_api_host="https://x.example.com/")
        assert settings.qweather_base_url == "https://x.example.com"


class TestParseWarnings:
    def test_fields_are_moved_not_rewritten(self) -> None:
        warnings = qweather.parse_warnings(WARNING_PAYLOAD, "https://example.invalid")

        assert len(warnings) == 1
        item = warnings[0]
        assert item["title"] == "大风蓝色预警信号"
        assert item["level"] == "蓝色"
        assert item["issuer"] == "正镶白旗气象台"
        assert item["issued_at"] == "2026-11-15T11:00+08:00"
        assert item["text"] == WARNING_PAYLOAD["warning"][0]["text"]  # 原文一字不差
        assert "不得改写" in item["policy"]

    def test_empty_warning_list(self) -> None:
        assert qweather.parse_warnings({"code": "204"}, "u") == []


class TestFetchWarnings:
    @respx.mock
    async def test_success(self) -> None:
        respx.get(qweather.warning_url(SETTINGS)).mock(
            return_value=httpx.Response(200, json=WARNING_PAYLOAD)
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is True
        assert result["warnings"][0]["issuer"] == "正镶白旗气象台"
        assert result["source_url"].startswith("https://demo.re.qweatherapi.com")

    @respx.mock
    async def test_no_active_warning_is_available_but_empty(self) -> None:
        respx.get(qweather.warning_url(SETTINGS)).mock(
            return_value=httpx.Response(200, json={"code": "204"})
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is True
        assert result["warnings"] == []

    @respx.mock
    async def test_forbidden_is_explained(self) -> None:
        respx.get(qweather.warning_url(SETTINGS)).mock(
            return_value=httpx.Response(
                403, json={"error": {"status": 403, "title": "Invalid Host"}}
            )
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is False
        assert "403" in result["error"]

    @pytest.mark.parametrize(
        ("code", "needle"), [("401", "无效"), ("402", "每日访问次数"), ("403", "权限")]
    )
    async def test_business_codes(self, code: str, needle: str, monkeypatch) -> None:
        async def fake_get(*_: object, **__: object) -> httpx.Response:
            return httpx.Response(200, json={"code": code})

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is False
        assert needle in result["error"]

    async def test_without_key_returns_unavailable(self) -> None:
        result = await qweather.fetch_warnings(42.3, 115.0, settings=Settings(_env_file=None))

        assert result["available"] is False
        assert "SKYLENS_QWEATHER_KEY" in result["reason"]
