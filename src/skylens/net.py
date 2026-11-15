"""创建 HTTP client 的唯一入口。

Windows 上 ``ssl.create_default_context()`` 单次约 1.4 s（要枚举系统证书库），
而 httpx 会**每个 transport 各建一个上下文**（默认 + 代理），一次 ``pack`` 能花掉 2.7 s+。
所以这里把 SSL 上下文做成进程级单例，所有 client 共用。

``trust_env`` 交给配置：需要走系统代理（访问 aviationweather / JMA 时常见）就保持 true。
"""

from __future__ import annotations

import ssl
from functools import lru_cache

import httpx

from skylens.providers import registry
from skylens.settings import Settings


@lru_cache(maxsize=1)
def default_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def create_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout_s,
        headers={"User-Agent": registry.USER_AGENT},
        verify=default_ssl_context(),
        trust_env=settings.trust_env,
    )
