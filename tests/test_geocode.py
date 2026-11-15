"""地理编码测试：Nominatim 优先（实测对中文镇级地名最稳）、候选全返回、失败不抛。"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import geocode, registry
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
    async def test_qweather_wins_when_key_configured(self) -> None:
        respx.get(registry.QWEATHER_GEOAPI).mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [
                        {
                            "name": "明安图",
                            "lat": "42.29",
                            "lon": "114.99",
                            "adm1": "内蒙古自治区",
                            "adm2": "锡林郭勒盟",
                        }
                    ],
                },
            )
        )
        result = await geocode.geocode("明安图镇", settings=_settings(qweather_key="k"))

        assert result["geocode_source"] == "qweather"
        assert result["admin"] == "内蒙古自治区 锡林郭勒盟 明安图"

    @respx.mock
    async def test_no_result_returns_error_dict(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(return_value=httpx.Response(200, json=[]))
        respx.get(registry.OPEN_METEO_GEOCODING).mock(
            return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
        )
        result = await geocode.geocode("不存在的地方", settings=_settings())

        assert result["error"] == "geocode_not_found"

    @respx.mock
    async def test_network_error_is_not_raised(self) -> None:
        respx.get(registry.NOMINATIM_SEARCH).mock(side_effect=httpx.ConnectError("boom"))
        result = await geocode.geocode("明安图镇", settings=_settings())

        assert result["error"] == "geocode_failed"
        assert "boom" in result["detail"]
