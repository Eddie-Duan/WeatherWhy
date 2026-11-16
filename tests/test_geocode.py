"""地理编码测试：Nominatim 优先（实测对中文镇级地名最稳）、候选全返回、失败不抛。"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import geocode, qweather, registry
from skylens.settings import Settings

NOMINATIM_HITS = [
    {
        "name": "明安图镇",
        "lat": "42.2984361",
        "lon": "115.0013690",
        "display_name": "明安图镇, 正镶白旗, 锡林郭勒盟, 内蒙古自治区, 中国",
        "address": {
            "town": "明安图镇",
            "county": "正镶白旗",
            "state": "内蒙古自治区",
        },
    },
    {
        "name": "明安图镇",
        "lat": "42.3282089",
        "lon": "114.9359473",
        "display_name": "明安图镇, 正镶白旗, 锡林郭勒盟, 内蒙古自治区, 中国",
        "address": {"town": "明安图镇", "county": "正镶白旗", "state": "内蒙古自治区"},
    },
]

OPEN_METEO_HITS = {
    "results": [
        {
            "name": "锡林浩特机场",
            "latitude": 43.9156,
            "longitude": 115.964,
            "elevation": 1013.0,
            "country": "中国",
            "admin1": "内蒙古",
            "admin2": "锡林郭勒盟",
        }
    ]
}


def _settings(**env: str) -> Settings:
    return Settings(_env_file=None, **env) if env else Settings(_env_file=None)


class TestNominatimFirst:
    @respx.mock
    async def test_picks_best_candidate_and_keeps_all(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(
            return_value=httpx.Response(200, json=NOMINATIM_HITS)
        )
        result = await geocode.geocode("明安图镇", settings=_settings())

        assert result["geocode_source"] == "nominatim"
        assert result["lat"] == pytest.approx(42.2984)
        assert result["lon"] == pytest.approx(115.0014)
        assert result["admin"] == "内蒙古自治区 正镶白旗"
        assert len(result["geocode_candidates"]) == 2
        assert 0.5 < result["geocode_confidence"] <= 0.99

    @respx.mock
    async def test_falls_back_to_open_meteo_when_nominatim_empty(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(return_value=httpx.Response(200, json=[]))
        respx.get(registry.OPEN_METEO_GEOCODING).mock(
            return_value=httpx.Response(200, json=OPEN_METEO_HITS)
        )
        result = await geocode.geocode("锡林浩特", settings=_settings())

        assert result["geocode_source"] == "open_meteo"
        assert result["elevation_m"] == 1013.0

    @respx.mock
    async def test_qweather_is_fallback_not_primary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """实测：和风把「明安图镇」匹配成吉林安图，所以只有 Nominatim 没结果时才用它。"""
        settings = _settings(qweather_key="k", qweather_api_host="demo.re.qweatherapi.com")
        respx.get(registry.NOMINATIM_SEARCH).mock(return_value=httpx.Response(200, json=[]))
        respx.get(qweather.geo_url(settings)).mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [
                        {
                            "name": "正镶白旗",
                            "lat": "42.28681",
                            "lon": "115.03143",
                            "adm1": "内蒙古自治区",
                            "adm2": "锡林郭勒盟",
                        }
                    ],
                },
            )
        )
        result = await geocode.geocode("正镶白旗", settings=settings)

        assert result["geocode_source"] == "qweather"
        assert result["admin"] == "内蒙古自治区 锡林郭勒盟 正镶白旗"

    @respx.mock
    async def test_nominatim_beats_qweather_for_towns(self) -> None:
        settings = _settings(qweather_key="k", qweather_api_host="demo.re.qweatherapi.com")
        respx.get(registry.NOMINATIM_SEARCH).mock(
            return_value=httpx.Response(200, json=NOMINATIM_HITS)
        )
        result = await geocode.geocode("明安图镇", settings=settings)

        assert result["geocode_source"] == "nominatim"
        assert result["lat"] == pytest.approx(42.2984)

    @respx.mock
    async def test_no_result_returns_error_dict(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(return_value=httpx.Response(200, json=[]))
        respx.get(registry.OPEN_METEO_GEOCODING).mock(
            return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
        )
        result = await geocode.geocode("不存在的地方", settings=_settings())

        assert result["error"] == "geocode_not_found"

    @respx.mock
    async def test_nominatim_timeout_does_not_kill_the_chain(self) -> None:
        """实测教训：Nominatim 一超时，整条链就 geocode_failed。现在必须逐源降级。"""
        respx.get(registry.NOMINATIM_SEARCH).mock(side_effect=httpx.ConnectTimeout("timed out"))
        respx.get(registry.OPEN_METEO_GEOCODING).mock(
            return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
        )
        result = await geocode.geocode("明安图镇", settings=_settings())

        # 网络全挂 → 本地兜底表接住
        assert result["geocode_source"] == "local_table"
        assert result["lat"] == pytest.approx(42.2984)
        assert result.get("geocode_note")
        assert result["geocode_attempt_errors"][0]["source"] == "nominatim"

    @respx.mock
    async def test_implausible_qweather_match_is_rejected(self) -> None:
        """和风把「明安图镇」匹配到吉林安图（43.11,128.90），必须被合理性规则挡掉。"""
        settings = _settings(qweather_key="k", qweather_api_host="demo.re.qweatherapi.com")
        respx.get(registry.NOMINATIM_SEARCH).mock(side_effect=httpx.ConnectError("boom"))
        respx.get(qweather.geo_url(settings)).mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [
                        {
                            "name": "安图",
                            "lat": "43.11",
                            "lon": "128.90",
                            "adm1": "吉林省",
                            "adm2": "延边朝鲜族自治州",
                        }
                    ],
                },
            )
        )
        respx.get(registry.OPEN_METEO_GEOCODING).mock(
            return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
        )
        result = await geocode.geocode("明安图镇", settings=settings)

        assert result["geocode_source"] == "local_table"
        assert result["name"] == "明安图镇"

    @respx.mock
    async def test_local_table_survives_total_network_failure(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(side_effect=httpx.ConnectTimeout("x"))
        respx.get(registry.OPEN_METEO_GEOCODING).mock(side_effect=httpx.ConnectTimeout("x"))
        result = await geocode.geocode("锡林浩特", settings=_settings())

        assert result["geocode_source"] == "local_table"
        assert result["name"] == "锡林浩特市"
        assert result["geocode_confidence"] == 0.7
