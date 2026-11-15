"""配置层：环境变量 > ``.env`` > 默认值。

沿用旧仓 ``config.py`` 的「结构 + 优先级 + 密钥落盘 chmod 600」思路，
换成 ``pydantic-settings``。所有变量以 ``SKYLENS_`` 为前缀。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """运行期配置。缺失 LLM key 不阻止启动，只阻止真正调用 LLM。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SKYLENS_",
        extra="ignore",
    )

    # --- LLM（OpenAI 兼容，key 只在服务端）---
    llm_provider: Literal["deepseek", "qwen"] = "deepseek"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 3000  # 输出契约有 9 个字段，2000 会被截断（实测）
    llm_temperature: float = 0.3

    # --- 国内数据源（可选，缺省回退 Open-Meteo）---
    qweather_key: SecretStr | None = None
    tianditu_key: str | None = None

    # --- 运行 ---
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "skylens")
    log_level: str = "INFO"
    http_timeout_s: float = 10.0
    http_retries: int = 2
    request_deadline_s: float = 20.0
    trust_env: bool = True  # 读系统代理；访问 aviationweather / JMA 时常需要

    @field_validator("cache_dir")
    @classmethod
    def _expand_cache_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def llm_api_key_value(self) -> str | None:
        """密钥明文只在这一处取出，避免到处 ``.get_secret_value()``。"""
        if self.llm_api_key is None:
            return None
        value = self.llm_api_key.get_secret_value().strip()
        return value or None

    def require_llm_key(self) -> str:
        value = self.llm_api_key_value
        if value is None:
            raise RuntimeError(
                "缺少 SKYLENS_LLM_API_KEY：请先复制 .env.example 为 .env 并填写，"
                "或运行 `skylens configure`。"
            )
        return value

    def ensure_cache_dir(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    def setup_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        )


_ENV_FILE_HEADER = "# 由 skylens configure 写入。不要提交到版本库。\n"


def save_secret_to_env(name: str, value: str, env_file: Path | None = None) -> Path:
    """把 ``SKYLENS_<NAME>`` 写入 ``.env``（权限 0600），已存在则原地替换。

    沿用旧仓 ``save_api_key()`` 的做法：密钥只落盘到被 gitignore 的文件。
    """
    path = env_file or Path.cwd() / ".env"
    key = name if name.startswith("SKYLENS_") else f"SKYLENS_{name}"
    line = f"{key}={value}"

    existing: list[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()

    replaced = False
    for index, old in enumerate(existing):
        if old.split("=", 1)[0].strip() == key:
            existing[index] = line
            replaced = True
            break
    if not replaced:
        existing.append(line)

    body = "\n".join(existing).rstrip("\n") + "\n"
    if not body.startswith("#"):
        body = _ENV_FILE_HEADER + body
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows 上权限位语义有限，失败不致命
        logger.debug("chmod 0600 未生效：%s", path)
    return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例；测试里改环境变量后请调用 ``get_settings.cache_clear()``。"""
    return Settings()
