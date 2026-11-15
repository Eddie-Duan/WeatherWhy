"""METAR 测试：最近站点、英制→公制、VRB 风向、代表性分级、24h 趋势。

单位口径以真实响应为准：``wspd`` 节、``visib`` 法定英里、``clouds[].base`` 英尺、``altim`` hPa。
"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import metar, registry
from skylens.settings import Settings


def report(
    icao: str,
    *,
    lat: float,
    lon: float,
    temp: float,
    dewp: float,
    wdir: float | str,
    wspd: float,
    altim: float,
    report_time: str,
    elev: float = 1000.0,
    visib: float | str = "6+",
    clouds: list[dict] | None = None,
    wx: str | None = None,
) -> dict:
    return {
        "icaoId": icao,
        "name": f"{icao} airport",
        "lat": lat,
        "lon": lon,
        "elev": elev,
        "temp": temp,
        "dewp": dewp,
        "wdir": wdir,
        "wspd": wspd,
        "altim": altim,
        "reportTime": report_time,
        "visib": visib,
        "clouds": clouds or [],
        "wxString": wx,
        "rawOb": f"METAR {icao}",
    }


NEAR = report(
    "ZBXH",
    lat=43.9156,
    lon=115.964,
    temp=-3.2,
    dewp=-12.0,
    wdir=320,
    wspd=16.5,
    altim=1032.1,
    report_time="2026-11-15T08:00:00.000Z",
    elev=1010,
    clouds=[{"cover": "FEW", "base": 1500}],
    wx="-SN",
)
FAR = report(
    "ZBAA",
    lat=40.08,
    lon=116.60,
    temp=10.0,
    dewp=3.0,
    wdir=180,
    wspd=8.0,
    altim=1025.0,
    report_time="2026-11-15T08:00:00.000Z",
    elev=31,
)


class TestUnitsAndParsing:
    def test_knots_to_ms_and_feet_to_metres(self) -> None:
        assert metar.num("16.5") == 16.5
        assert metar.num("VRB") is None
        assert metar._knots_to_ms(16.5) == pytest.approx(8.5, abs=0.05)
        assert metar._cloud_layer({"cover": "FEW", "base": 1500})["base_m"] == 457

    def test_visibility_accepts_string_and_number(self) -> None:
        assert metar.visibility_m("6+") == 9656
        assert metar.visibility_m(1.99) == 3203
        assert metar.visibility_m(None) is None

    def test_relative_humidity_from_dewpoint(self) -> None:
        assert metar.relative_humidity(-3.2, -12.0) == 51


class TestFetchNearest:
    @respx.mock
    async def test_picks_nearest_station_and_converts_units(self) -> None:
        respx.get(registry.METAR_API).mock(return_value=httpx.Response(200, json=[FAR, NEAR]))
        result = await metar.fetch_nearest(
            42.3, 115.0, place="明安图镇", elevation_m=1350, settings=Settings(_env_file=None)
        )

        assert result["available"] is True
        assert result["station"]["id"] == "ZBXH"
        assert result["temp_c"] == -3.2
        assert result["wind_speed_ms"] == pytest.approx(8.5, abs=0.05)
        assert result["pressure_msl_hpa"] == 1032.1
        assert result["cloud_layers"][0]["base_m"] == 457
        assert result["visibility_m"] == 9656
        assert result["weather_code"] == "-SN"
        assert result["representativeness"]["level"] == "低"
        assert "明安图镇" in result["representativeness"]["reason"]
        assert result["source"] == "METAR ZBXH"

    @respx.mock
    async def test_variable_wind_direction_is_none_not_crash(self) -> None:
        vrb = {**NEAR, "wdir": "VRB"}
        respx.get(registry.METAR_API).mock(return_value=httpx.Response(200, json=[vrb]))
        result = await metar.fetch_nearest(43.9, 115.9, settings=Settings(_env_file=None))

        assert result["wind_dir_deg"] is None

    @respx.mock
    async def test_trend_over_history(self) -> None:
        older = report(
            "ZBXH",
            lat=43.9156,
            lon=115.964,
            temp=2.0,
            dewp=-8.0,
            wdir=300,
            wspd=10.0,
            altim=1028.0,
            report_time="2026-11-15T00:00:00.000Z",
            elev=1010,
        )
        respx.get(registry.METAR_API).mock(return_value=httpx.Response(200, json=[older, NEAR]))
        result = await metar.fetch_nearest(43.9, 115.9, settings=Settings(_env_file=None))

        trend = result["trend_24h"]
        assert trend["temp_change_c"] == -5.2
        assert trend["pressure_change_hpa"] == 4.1
        assert trend["wind_dir_change_deg"] == 20
        assert "近 24h 序列" in trend["basis"]
        assert result["pressure_trend_3h_hpa"] == pytest.approx(4.1)
        assert "pressure_trend_3h_hpa" not in trend

    @respx.mock
    async def test_no_station_returns_available_false(self) -> None:
        respx.get(registry.METAR_API).mock(return_value=httpx.Response(204))
        result = await metar.fetch_nearest(42.3, 115.0, settings=Settings(_env_file=None))

        assert result["available"] is False
        assert "无可用 METAR" in result["error"]

    @respx.mock
    async def test_network_error_is_not_raised(self) -> None:
        respx.get(registry.METAR_API).mock(side_effect=httpx.ConnectError("down"))
        result = await metar.fetch_nearest(42.3, 115.0, settings=Settings(_env_file=None))

        assert result["available"] is False
        assert "down" in result["error"]


class TestRepresentativeness:
    @pytest.mark.parametrize(
        ("distance", "delta", "level"),
        [(20.0, 100.0, "高"), (120.0, 200.0, "中"), (300.0, 100.0, "低"), (10.0, 900.0, "低")],
    )
    def test_levels(self, distance: float, delta: float, level: str) -> None:
        assert metar.representativeness(distance, delta)["level"] == level

    def test_reason_mentions_distance(self) -> None:
        assert "281 km" in metar.representativeness(281.0, 320.0)["reason"]
