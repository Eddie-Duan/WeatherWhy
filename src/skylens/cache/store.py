"""按 URL+参数落盘的 TTL 缓存（JSON 文件，原子写入）。

TTL 取值见 ``docs/TECHNICAL_DESIGN.md`` §8。缓存只服务单用户本地场景：
不对外暴露、不跨机器同步、不缓存密钥相关内容。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TTL:
    """各类数据的缓存寿命（秒）。"""

    geocode: int = 30 * 86400
    metar: int = 600
    forecast: int = 3600
    pressure_levels: int = 3 * 3600
    charts: int = 3 * 3600
    enso: int = 7 * 86400
    fact_pack: int = 900


def make_key(url: str, params: dict[str, Any] | None = None) -> str:
    """稳定的缓存键：URL + 排序后的参数。"""
    payload = (
        url if not params else f"{url}?{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TTLCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str, ttl: int) -> Any | None:
        path = self._path(key)
        try:
            if time.time() - path.stat().st_mtime > ttl:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def cache_get(cache: TTLCache | None, key: str, ttl: int) -> Any | None:
    return None if cache is None else cache.get(key, ttl)


def cache_set(cache: TTLCache | None, key: str, value: Any) -> None:
    if cache is not None:
        cache.set(key, value)
