"""和风天气预警测试：新 weatheralert 接口、字段原样搬运、无 key 时不编造。"""

from __future__ import annotations

import httpx
import respx

from skylens.providers import qweather
from skylens.settings import Settings

SETTINGS = Settings(_env_file=None, qweather_key="k", qweather_api_host="demo.re.qweatherapi.com")

ALERT_TEXT = (
    "正镶白旗气象台2026年11月15日18时12分发布暴雪蓝色预警信号："
    "12小时内正镶白旗降雪量将达4毫米以上，野外伴有吹雪，对交通或者农牧业有影响。"
)

PAYLOAD = {
    "metadata": {
        "tag": "t",
        "zeroResult": False,
        "attributions": [
            "国家预警信息发布中心",
            "当前预警数据可能存在延迟或信息过时，以官方数据发布为准。",
        ],
    },
    "alerts": [
        {
            "id": "202611151815442856502454",
            "senderName": "正镶白旗气象台",
            "issuedTime": "2026-11-15T10:15Z",
            "effectiveTime": "2026-11-15T10:22Z",
            "expireTime": "2026-11-16T10:15Z",
            "messageType": {"code": "alert", "supersedes": []},
            "eventType": {"name": "暴雪", "code": "1004"},
            "color": {"code": "blue"},
            "headline": "正镶白旗气象台发布暴雪蓝色预警",
            "description": ALERT_TEXT,
            "instruction": "请有关单位和人员做好防范准备。",
        }
    ],
}


class TestUrls:
    def test_geo_url_uses_configured_host(self) -> None:
        assert qweather.geo_url(SETTINGS) == "https://demo.re.qweatherapi.com/geo/v2/city/lookup"

    def test_alert_url_puts_coordinates_in_path(self) -> None:
        url = qweather.alert_url(SETTINGS, 42.2984371, 115.001369)
        assert url == "https://demo.re.qweatherapi.com/weatheralert/v1/current/42.30/115.00"

    def test_empty_host_falls_back_to_legacy(self) -> None:
        settings = Settings(_env_file=None, qweather_api_host="")
        assert settings.qweather_base_url == "https://devapi.qweather.com"


class TestParseAlerts:
    def test_fields_are_moved_not_rewritten(self) -> None:
        warnings = qweather.parse_alerts(PAYLOAD, "https://example.invalid")

        assert len(warnings) == 1
        item = warnings[0]
        assert item["title"] == "正镶白旗气象台发布暴雪蓝色预警"
        assert item["level"] == "蓝色"  # color.code → 中文
        assert item["type"] == "暴雪"
        assert item["issuer"] == "正镶白旗气象台"
        assert item["issued_at"] == "2026-11-15T18:15:00+08:00"  # UTC → +08:00
        assert item["start_time"] == "2026-11-15T18:22:00+08:00"
        assert item["text"] == ALERT_TEXT  # 原文一字不差
        assert item["attribution"] == "国家预警信息发布中心"
        assert "不得改写" in item["policy"]

    def test_zero_result(self) -> None:
        assert qweather.parse_alerts({"metadata": {"zeroResult": True}, "alerts": []}, "u") == []


class TestFetchWarnings:
    @respx.mock
    async def test_success(self) -> None:
        respx.get(qweather.alert_url(SETTINGS, 42.3, 115.0)).mock(
            return_value=httpx.Response(200, json=PAYLOAD)
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is True
        assert result["warnings"][0]["issuer"] == "正镶白旗气象台"
        assert "国家预警信息发布中心" in result["attribution"]
        assert result["source_url"].startswith("https://demo.re.qweatherapi.com/weatheralert")

    @respx.mock
    async def test_no_active_warning(self) -> None:
        respx.get(qweather.alert_url(SETTINGS, 42.3, 115.0)).mock(
            return_value=httpx.Response(200, json={"metadata": {"zeroResult": True}, "alerts": []})
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is True
        assert result["warnings"] == []

    @respx.mock
    async def test_http_error_is_explained(self) -> None:
        respx.get(qweather.alert_url(SETTINGS, 42.3, 115.0)).mock(
            return_value=httpx.Response(403, json={"error": {"title": "Deprecated"}})
        )
        result = await qweather.fetch_warnings(42.3, 115.0, settings=SETTINGS)

        assert result["available"] is False
        assert "HTTP 403" in result["error"]
        assert "Deprecated" in result["error"]

    async def test_without_key_returns_unavailable(self) -> None:
        result = await qweather.fetch_warnings(42.3, 115.0, settings=Settings(_env_file=None))

        assert result["available"] is False
        assert "SKYLENS_QWEATHER_KEY" in result["reason"]
