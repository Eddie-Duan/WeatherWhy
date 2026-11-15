"""Provider 契约：``Sourced`` + ``Provider`` Protocol。

硬规则（全项目适用，见 ``docs/TECHNICAL_DESIGN.md`` §4）：

- Provider **不得**抛异常出界，失败返回 ``{"error": ..., "provider": name}``；
- Provider **不得**做单位换算，换算统一在 ``core/units.py``；
- Provider **不得**调用 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Sourced:
    """带出处的数值——全项目唯一允许跨层传递的数值容器。"""

    value: float | str | None
    unit: str
    source: str  # "METAR ZBXH" / "Open-Meteo ecmwf_ifs025"
    source_url: str
    valid_time: str  # ISO8601，数据本身的有效时刻
    fetched_at: str  # ISO8601，我们抓取的时刻
    stale_seconds: int = 0  # 允许的过期容忍；超过则在 UI 标灰

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "source_url": self.source_url,
            "valid_time": self.valid_time,
            "fetched_at": self.fetched_at,
            "stale_seconds": self.stale_seconds,
        }


@dataclass(frozen=True)
class ProviderError:
    """失败也是数据：由 fact_pack 记进 ``provenance.missing``，不向上抛。"""

    provider: str
    error: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "error": self.error, "detail": self.detail}


@runtime_checkable
class Provider(Protocol):
    name: str

    async def available(self) -> bool: ...

    async def fetch(self, lat: float, lon: float, **kw: Any) -> dict[str, Any]: ...


@dataclass
class ProviderResult:
    """``fact_pack`` 编排时每个 provider 的落账单位（耗时进 provenance）。"""

    name: str
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0
