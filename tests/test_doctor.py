"""doctor 测试：只测纯逻辑（脱敏、关键项判定），网络检查由真实命令覆盖。"""

from __future__ import annotations

from skylens.doctor import Check, all_critical_ok, mask_secret


class TestMaskSecret:
    def test_never_returns_full_secret(self) -> None:
        masked = mask_secret("sk-1234567890abcdef")
        assert "234567890" not in masked
        assert masked.startswith("已配置")
        assert "sk-" in masked

    def test_short_secret_only_length(self) -> None:
        assert mask_secret("sk-1234") == "已配置（7 字符）"

    def test_missing(self) -> None:
        assert mask_secret(None) == "未配置"
        assert mask_secret("") == "未配置"


class TestAllCriticalOk:
    def test_critical_failure_blocks(self) -> None:
        checks = [
            Check("Python", True, critical=True),
            Check("LLM 配置", False, critical=True),
            Check("Open-Meteo", False),  # 非关键项失败不阻塞
        ]
        assert all_critical_ok(checks) is False

    def test_non_critical_failures_do_not_block(self) -> None:
        checks = [Check("Python", True, critical=True), Check("JMA", False)]
        assert all_critical_ok(checks) is True
