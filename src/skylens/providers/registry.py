"""外部端点与模式清单：旧仓硬编码在函数体里的 endpoint 全部收在这里。

换源、加模式、改地址都只动本文件（对应技术债清单 #2）。
"""

from __future__ import annotations

from dataclasses import dataclass

from skylens.cache.store import TTL

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
OPEN_METEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
METAR_API = "https://aviationweather.gov/api/data/metar"
# 和风天气 URL 由 settings.qweather_api_host 拼出（每账号一个 API Host），见 providers/qweather.py

USER_AGENT = (
    "skylens/0.1 (personal non-commercial weather reader; https://github.com/Eddie-Duan/WeatherWhy)"
)

TTLS = TTL()


@dataclass(frozen=True)
class ModelSpec:
    """一个预报模式。``name`` 必须与 Open-Meteo 的 model 标识一致。"""

    name: str
    label: str


DEFAULT_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("ecmwf_ifs025", "ECMWF IFS 0.25°"),
    ModelSpec("gfs_seamless", "GFS Seamless"),
    ModelSpec("icon_seamless", "ICON Seamless"),
    ModelSpec("gem_global", "GEM Global"),
)


class ModelRegistry:
    """可用模式清单；provider 只向这里要名字，不自己拼。"""

    def __init__(self, models: tuple[ModelSpec, ...] = DEFAULT_MODELS) -> None:
        self._models = models

    @property
    def specs(self) -> tuple[ModelSpec, ...]:
        return self._models

    @property
    def names(self) -> list[str]:
        return [spec.name for spec in self._models]

    def label(self, name: str) -> str:
        return next((spec.label for spec in self._models if spec.name == name), name)


def box_around(lat: float, lon: float, radius_deg: float) -> str:
    """METAR 的 bbox 参数：``lat_min,lon_min,lat_max,lon_max``（含边界）。"""
    lat_min = max(-90.0, lat - radius_deg)
    lat_max = min(90.0, lat + radius_deg)
    lon_min = max(-180.0, lon - radius_deg)
    lon_max = min(180.0, lon + radius_deg)
    return f"{lat_min:.3f},{lon_min:.3f},{lat_max:.3f},{lon_max:.3f}"
