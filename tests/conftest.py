"""测试共享夹具：一份形状最小但字段齐全的 fact_pack（M1+M2 契约）。"""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_pack() -> dict:
    return {
        "schema_version": "1.0",
        "fact_pack_id": "sha256:test",
        "generated_at": "2026-11-15T17:00:00+08:00",
        "location": {
            "query": "明安图镇",
            "name": "明安图镇",
            "admin": "内蒙古自治区 正镶白旗",
            "lat": 42.2984,
            "lon": 115.0014,
            "elevation_m": 1345.0,
            "timezone": "Asia/Shanghai",
            "geocode_source": "nominatim",
            "geocode_confidence": 0.85,
            "geocode_candidates": [],
        },
        "observed": {
            "available": True,
            "station": {
                "id": "ZBAA",
                "name": "Beijing Intl",
                "distance_km": 281,
                "elevation_m": 31,
            },
            "valid_time": "2026-11-15T17:00:00+08:00",
            "age_minutes": 6,
            "temp_c": 10.0,
            "dewpoint_c": 3.0,
            "rh_pct": 62.0,
            "pressure_msl_hpa": 1025.0,
            "pressure_trend_3h_hpa": 0.0,
            "wind_dir_deg": 180.0,
            "wind_speed_ms": 4.1,
            "wind_gust_ms": None,
            "cloud_layers": [],
            "visibility_m": 3492,
            "weather_code": "HZ",
            "source": "METAR ZBAA",
            "source_url": "https://example.invalid/metar?ids=ZBAA",
            "representativeness": {"level": "低", "reason": "281 km，不能代表当地局地实况"},
            "local": {
                "kind": "格点实况（非站点观测）",
                "valid_time": "2026-11-15T17:00:00+08:00",
                "temp_c": -7.2,
                "feels_like_c": -12.9,
                "dewpoint_c": -9.1,
                "rh_pct": 86.0,
                "pressure_msl_hpa": 1026.9,
                "wind_dir_deg": 271.0,
                "wind_speed_ms": 8.3,
                "weather_text": "阴",
                "source": "和风天气 current（格点实况）",
            },
            "temp_adjusted": {
                "temp_c": 1.5,
                "observed_station_temp_c": 10.0,
                "elevation_delta_m": 1314,
                "lapse_rate_c_per_km": 6.5,
                "method": "标准大气温度递减率",
                "confidence": "推断",
                "caveats": ["只修正海拔差", "不可替代观测"],
            },
        },
        "trend_24h": {"temp_change_c": -5.2, "pressure_change_hpa": 4.1, "basis": "METAR 近 24h"},
        "forecast": {
            "models": ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_global"],
            "elevation_m": 1345.0,
            "daily": [
                {
                    "date": "2026-11-16",
                    "temp_max": {"mean": -1.57, "p10": -2.21, "p90": -0.84, "spread": 1.37},
                    "temp_min": {"mean": -8.47, "p10": -10.67, "p90": -6.14, "spread": 4.53},
                    "precip_mm": {"mean": 0.45, "p10": 0.06, "p90": 0.96, "spread": 0.9},
                    "wind_max_ms": {"mean": 5.2, "p10": 4.58, "p90": 5.95, "spread": 1.37},
                }
            ],
            "agreement": {
                "temperature_max": {"level": "高", "spread": 1.37, "basis": "多模式"},
                "precipitation": {"level": "高", "spread": 0.9, "basis": "多模式"},
            },
        },
        "synoptic": {
            "h500_geopotential_m": 5503.0,
            "h500_anomaly_m": None,
            "t500_c": -23.8,
            "t850_c": -8.7,
            "wind850_dir_deg": 294.0,
            "wind850_speed_ms": 8.33,
            "valid_time": "2026-11-15T23:00+08:00",
            "source": "Open-Meteo pressure-level",
            "source_url": "https://example.invalid/pressure",
            "charts": [
                {
                    "title": "JMA 亚洲地面天气图（实况）",
                    "url": "https://example.invalid/jma.png",
                    "valid_time": "2026-11-15T14:00:00+08:00",
                    "license": "JMA 政府標準利用規約",
                    "kind": "地面天气图",
                }
            ],
            "pattern": {
                "label": "500hPa 平直西风，850hPa 西北气流",
                "confidence": "推断",
                "basis": ["synoptic.h500_geopotential_m", "synoptic.wind850_dir_deg"],
            },
        },
        "climate": {
            "season": "初冬",
            "enso": {
                "phase": "El Niño",
                "oni": 2.46,
                "month": "2026-09",
                "source": "NOAA CPC ONI",
                "source_url": "https://example.invalid/oni.txt",
            },
            "climate_normal": None,
        },
        "warnings": [],
        "provenance": {
            "providers": [
                {"name": "geocode", "ok": True, "latency_ms": 420},
                {"name": "open_meteo", "ok": True, "latency_ms": 810},
                {"name": "metar", "ok": True, "latency_ms": 240},
                {"name": "open_meteo_pressure", "ok": True, "latency_ms": 300},
                {"name": "charts", "ok": True, "latency_ms": 200},
                {"name": "enso", "ok": True, "latency_ms": 90},
            ],
            "missing": ["官方预警（需和风天气 key，M4 接入）"],
            "notes": ["离散度为多模式 p10–p90"],
        },
    }
