"""配置层测试：优先级（env > .env > 默认）、密钥不落 console、密钥写盘。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skylens.settings import Settings, save_secret_to_env


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """清掉外部 SKYLENS_* 变量，保证测试不受本机 .env/环境干扰。"""
    for key in list(os.environ):
        if key.startswith("SKYLENS_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestSettings:
    def test_defaults(self, env: pytest.MonkeyPatch) -> None:
        settings = Settings(_env_file=None)
        assert settings.llm_provider == "deepseek"
        assert settings.llm_model == "deepseek-chat"
        assert settings.llm_api_key_value is None
        assert settings.cache_dir.name == "skylens"

    def test_env_override_with_prefix(self, env: pytest.MonkeyPatch) -> None:
        env.setenv("SKYLENS_LLM_MODEL", "qwen-plus")
        env.setenv("SKYLENS_LOG_LEVEL", "DEBUG")
        settings = Settings(_env_file=None)
        assert settings.llm_model == "qwen-plus"
        assert settings.log_level == "DEBUG"

    def test_cache_dir_expands_home(self, env: pytest.MonkeyPatch) -> None:
        env.setenv("SKYLENS_CACHE_DIR", "~/custom-cache")
        settings = Settings(_env_file=None)
        assert "~" not in str(settings.cache_dir)
        assert settings.cache_dir.is_absolute()

    def test_missing_key_raises_actionable_error(self, env: pytest.MonkeyPatch) -> None:
        settings = Settings(_env_file=None)
        with pytest.raises(RuntimeError, match="SKYLENS_LLM_API_KEY"):
            settings.require_llm_key()

    def test_secret_never_printed(self, env: pytest.MonkeyPatch) -> None:
        env.setenv("SKYLENS_LLM_API_KEY", "sk-very-secret")
        settings = Settings(_env_file=None)
        assert "sk-very-secret" not in repr(settings)
        assert settings.llm_api_key_value == "sk-very-secret"
        assert settings.require_llm_key() == "sk-very-secret"

    def test_empty_key_is_treated_as_missing(self, env: pytest.MonkeyPatch) -> None:
        env.setenv("SKYLENS_LLM_API_KEY", "   ")
        settings = Settings(_env_file=None)
        assert settings.llm_api_key_value is None


class TestSaveSecretToEnv:
    def test_creates_file_with_header(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        save_secret_to_env("LLM_API_KEY", "sk-abc", env_file=env_file)

        text = env_file.read_text(encoding="utf-8")
        assert "不要提交到版本库" in text
        assert "SKYLENS_LLM_API_KEY=sk-abc" in text

    def test_updates_in_place_without_duplicating(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SKYLENS_LLM_MODEL=deepseek-chat\nSKYLENS_LLM_API_KEY=old\n", "utf-8")

        save_secret_to_env("LLM_API_KEY", "new", env_file=env_file)

        text = env_file.read_text(encoding="utf-8")
        assert text.count("SKYLENS_LLM_API_KEY=") == 1
        assert "SKYLENS_LLM_API_KEY=new" in text
        assert "SKYLENS_LLM_MODEL=deepseek-chat" in text
