"""fact_pack 契约测试：编排、缺失落账、内容哈希、JSON 合法性。

用注入的假 provider，不触网——真实网络链路由 CLI 端到端手测覆盖。
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from skylens.cache.store import TTLCache
from skylens.core import fact_pack
from skylens.settings import Settings

LOCATION = {
    "query": "明安图镇",
    "name": "明安图镇",
    "admin": "内蒙古自治区 正镶白旗",
    "lat": 42.2984,
    "lon": 115.0014,
    "elevation_m": None,
    "timezone": "Asia/Shanghai",
    "geocode_source": "nominatim",
    "geocode_confidence": 0.85,
    "geocode_candidates": [
        {
            "name": "明安图镇",
            "admin": "",
            "lat": 42.2984,
            "lon": 115.0014,
            "elevation_m": None,
            "score": 0.85,
        }
    ],
}

FORECAST = {
    "provider": "open_meteo",
    "models": ["ecmwf_ifs025", "gfs_seamless"],
    "elevation_m": 1345.0,
    "daily": [
        {
            "date": "2026-11-16",
            "temp_max": {"mean": 1.2, "p10": -1.0, "p90": 3.4, "spread": 4.4},
            "temp_min": {"mean": -11.5, "p10": -14.2, "p90": -9.0, "spread": 5.2},
            "precip_mm": {"mean": 0.0, "p10": 0.0, "p90": 0.4, "spread": 0.4},
            "wind_max_ms": {"mean": 11.0, "p10": 8.0, "p90": 14.0, "spread": 3.0},
        }
    ],
    "agreement": {"temperature_max": {"level": "中", "spread": 4.4}},
}

OBSERVED = {
    "provider": "metar",
    "available": True,
    "station": {"id": "ZBXH", "name": "Xilinhot", "distance_km": 150, "elevation_m": 1010},
    "valid_time": "2026-11-15T15:00:00+08:00",
    "age_minutes": 18,
    "temp_c": -3.2,
    "dewpoint_c": -12.0,
    "rh_pct": 51.0,
    "pressure_msl_hpa": 1032.1,
    "wind_dir_deg": 320.0,
    "wind_speed_ms": 8.5,
    "wind_gust_ms": 13.0,
    "cloud_layers": [{"cover": "FEW", "base_m": 457}],
    "visibility_m": 20000,
    "weather_code": "-SN",
    "source": "METAR ZBXH",
    "source_url": "https://example.invalid/metar",
    "representativeness": {"level": "低", "reason": "150 km，不能代表当地局地实况"},
    "trend_24h": {"temp_change_c": -6.1, "pressure_change_hpa": 3.2, "basis": "METAR 近 24h"},
}


def settings() -> Settings:
    return Settings(_env_file=None)


async def fake_geocode(query: str, **_: Any) -> dict[str, Any]:
    return dict(LOCATION)


async def fake_forecast(lat: float, lon: float, **_: Any) -> dict[str, Any]:
    return dict(FORECAST)


async def fake_metar(lat: float, lon: float, **_: Any) -> dict[str, Any]:
    return dict(OBSERVED)


async def build(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "settings": settings(),
        "cache": TTLCache(Path(tempfile.gettempdir()) / "skylens-test-cache"),
        "geocoder": fake_geocode,
        "forecaster": fake_forecast,
        "observer": fake_metar,
    }
    kwargs.update(overrides)
    return await fact_pack.build_fact_pack("明安图镇", **kwargs)


class TestContract:
    async def test_top_level_keys_match_design(self) -> None:
        pack = await build()
        assert set(pack) == {
            "schema_version",
            "fact_pack_id",
            "generated_at",
            "location",
            "observed",
            "trend_24h",
            "forecast",
            "synoptic",
            "climate",
            "warnings",
            "provenance",
        }
        assert pack["schema_version"] == "1.0"
        assert pack["fact_pack_id"].startswith("sha256:")

    async def test_observed_and_trend_are_wired(self) -> None:
        pack = await build()
        assert pack["observed"]["temp_c"] == -3.2
        assert pack["observed"]["representativeness"]["level"] == "低"
        assert pack["trend_24h"]["temp_change_c"] == -6.1

    async def test_forecast_carries_models_and_agreement(self) -> None:
        pack = await build()
        assert pack["forecast"]["models"] == ["ecmwf_ifs025", "gfs_seamless"]
        assert pack["forecast"]["agreement"]["temperature_max"]["level"] == "中"

    async def test_unimplemented_sections_are_null_and_listed_as_missing(self) -> None:
        pack = await build()
        assert pack["synoptic"] is None
        assert pack["climate"] is None
        assert pack["warnings"] == []
        assert any("M2" in item for item in pack["provenance"]["missing"])

    async def test_elevation_falls_back_to_forecast_grid(self) -> None:
        pack = await build()
        assert pack["location"]["elevation_m"] == 1345.0
        assert any("海拔" in note for note in pack["provenance"]["notes"])

    async def test_provenance_records_every_provider(self) -> None:
        pack = await build()
        names = [entry["name"] for entry in pack["provenance"]["providers"]]
        assert names == ["geocode", "open_meteo", "metar"]
        assert all(entry["ok"] for entry in pack["provenance"]["providers"])


class TestFailureHandling:
    async def test_forecast_failure_is_missing_not_crash(self) -> None:
        async def broken(lat: float, lon: float, **_: Any) -> dict[str, Any]:
            return {"error": "HTTP 502", "provider": "open_meteo"}

        pack = await build(forecaster=broken)
        assert pack["forecast"] is None
        assert any("多模式预报" in item for item in pack["provenance"]["missing"])
        assert pack["provenance"]["providers"][1]["ok"] is False

    async def test_metar_failure_keeps_pack(self) -> None:
        async def broken(lat: float, lon: float, **_: Any) -> dict[str, Any]:
            return {"provider": "metar", "available": False, "error": "无站点"}

        pack = await build(observer=broken)
        assert pack["observed"]["available"] is False
        assert pack["trend_24h"] is None
        assert any("本地实况" in item for item in pack["provenance"]["missing"])

    async def test_geocode_failure_returns_error(self) -> None:
        async def broken(query: str, **_: Any) -> dict[str, Any]:
            return {"error": "geocode_not_found", "query": query}

        pack = await build(geocoder=broken)
        assert pack["error"] == "geocode_not_found"


class TestSerialisation:
    async def test_nan_becomes_null_and_json_is_valid(self) -> None:
        nan_forecast = json.loads(json.dumps(FORECAST))
        nan_forecast["daily"][0]["temp_max"] = {
            "mean": math.nan,
            "p10": math.nan,
            "p90": math.nan,
            "spread": math.nan,
        }
        pack = await build(forecaster=lambda *a, **k: _return(nan_forecast))
        text = json.dumps(pack, ensure_ascii=False, allow_nan=False)  # 不允许 NaN
        assert "NaN" not in text
        assert json.loads(text)["forecast"]["daily"][0]["temp_max"]["mean"] is None

    async def test_fact_pack_id_is_content_hash(self) -> None:
        first = await build()
        second = await build()
        assert first["fact_pack_id"] == second["fact_pack_id"]

        changed = dict(FORECAST)
        changed["models"] = ["ecmwf_ifs025"]
        third = await build(forecaster=lambda *a, **k: _return(changed))
        assert third["fact_pack_id"] != first["fact_pack_id"]


async def _return(value: dict[str, Any]) -> dict[str, Any]:
    return value
