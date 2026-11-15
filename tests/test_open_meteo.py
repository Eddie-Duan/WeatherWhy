"""Open-Meteo 多模式预报测试：模式后缀解析、多模式离散度、失败降级。"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import open_meteo, registry
from skylens.settings import Settings


def _payload(*, with_second_model: bool = True) -> dict:
    daily = {
        "time": ["2026-11-15", "2026-11-16"],
        "temperature_2m_max_ecmwf_ifs025": [-2.6, -2.8],
        "temperature_2m_min_ecmwf_ifs025": [-8.4, -7.3],
        "precipitation_sum_ecmwf_ifs025": [0.2, 7.3],
        "wind_speed_10m_max_ecmwf_ifs025": [5.23, 6.68],
    }
    if with_second_model:
        daily.update(
            {
                "temperature_2m_max_gfs_seamless": [-1.8, -2.6],
                "temperature_2m_min_gfs_seamless": [-5.6, -8.2],
                "precipitation_sum_gfs_seamless": [0.0, 8.4],
                "wind_speed_10m_max_gfs_seamless": [6.26, 7.72],
            }
        )
    return {"elevation": 1345.0, "timezone": "Asia/Shanghai", "daily": daily}


class TestBuildDaily:
    def test_computes_mean_and_spread_across_models(self) -> None:
        daily = open_meteo.build_daily(_payload()["daily"], ["ecmwf_ifs025", "gfs_seamless"])

        assert [day["date"] for day in daily] == ["2026-11-15", "2026-11-16"]
        assert daily[0]["temp_max"]["mean"] == -2.2
        assert daily[0]["temp_max"]["spread"] == pytest.approx(0.64, abs=0.01)
        assert daily[0]["temp_max"]["p10"] < daily[0]["temp_max"]["p90"]

    def test_missing_variable_in_one_model_is_tolerated(self) -> None:
        payload = _payload(with_second_model=False)
        payload["daily"].pop("precipitation_sum_ecmwf_ifs025")
        daily = open_meteo.build_daily(payload["daily"], ["ecmwf_ifs025"])

        assert daily[0]["precip_mm"]["mean"] is None
        assert daily[0]["temp_max"]["mean"] == -2.6

    def test_unknown_model_yields_nan_turned_into_none(self) -> None:
        daily = open_meteo.build_daily(_payload()["daily"], ["not_a_model"])
        assert daily[0]["temp_max"]["mean"] is None

    def test_negative_precipitation_is_clamped_to_zero(self) -> None:
        payload = _payload()
        payload["daily"]["precipitation_sum_ecmwf_ifs025"] = [-0.1, 7.3]
        daily = open_meteo.build_daily(payload["daily"], ["ecmwf_ifs025", "gfs_seamless"])

        assert daily[0]["precip_mm"]["mean"] == 0.0
        assert daily[0]["precip_mm"]["p10"] == 0.0


class TestFetchDailyForecast:
    @respx.mock
    async def test_returns_agreement_and_no_nan(self) -> None:
        respx.get(registry.OPEN_METEO_FORECAST).mock(
            return_value=httpx.Response(200, json=_payload())
        )
        result = await open_meteo.fetch_daily_forecast(
            42.3,
            115.0,
            models=["ecmwf_ifs025", "gfs_seamless"],
            settings=Settings(_env_file=None),
        )

        assert result["provider"] == "open_meteo"
        assert result["elevation_m"] == 1345.0
        assert result["agreement"]["temperature_max"]["level"] == "高"
        assert "Open-Meteo" in result["agreement"]["temperature_max"]["basis"]
        assert result["source_url"].startswith(registry.OPEN_METEO_FORECAST)

    @respx.mock
    async def test_http_error_becomes_error_dict(self) -> None:
        respx.get(registry.OPEN_METEO_FORECAST).mock(return_value=httpx.Response(502))
        result = await open_meteo.fetch_daily_forecast(
            42.3, 115.0, settings=Settings(_env_file=None)
        )

        assert result["error"] == "HTTP 502"
        assert result["provider"] == "open_meteo"

    @respx.mock
    async def test_missing_daily_block_becomes_error_dict(self) -> None:
        respx.get(registry.OPEN_METEO_FORECAST).mock(
            return_value=httpx.Response(200, json={"elevation": 1.0})
        )
        result = await open_meteo.fetch_daily_forecast(
            42.3, 115.0, settings=Settings(_env_file=None)
        )

        assert "daily" in result["error"]
