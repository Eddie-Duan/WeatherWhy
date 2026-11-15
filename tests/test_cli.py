"""CLI 冒烟测试：M0 验收要求 ``python -m skylens`` 有输出、子命令可跑。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env.pop("SKYLENS_LLM_API_KEY", None)
    env["COLUMNS"] = "100"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "skylens", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )


def test_module_prints_version() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "skylens" in result.stdout
    assert "0.1.0" in result.stdout


def test_version_subcommand() -> None:
    assert _run("version").stdout.strip() == "skylens 0.1.0"


def test_help_lists_commands() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "configure" in result.stdout
    assert "sources" in result.stdout


def test_sources_runs_offline() -> None:
    result = _run("sources")
    assert result.returncode == 0, result.stderr
    assert "Open-Meteo" in result.stdout
