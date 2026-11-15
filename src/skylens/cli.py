"""命令行壳：cyclopts + rich（沿用旧仓用法，语义改写）。

M0 只保留与「取数无关」的三个子命令：``version`` / ``sources`` / ``configure``。
``where`` / ``pack`` / ``explain`` / ``serve`` / ``ask`` 分别落在 M1–M4。

刻意不做的事：把结构化参数拼成一句自然语言再交给模型解析（旧仓反模式，见 MIGRATION §2.7）。
"""

from __future__ import annotations

from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from skylens import __version__
from skylens.settings import get_settings, save_secret_to_env

app = App(
    name="skylens",
    help="天镜 SkyLens —— 多源天气事实包与可溯源解释（个人非商用，不发布预报）",
    version=__version__,
)
console = Console()


@app.command(name="version")
def version_cmd() -> None:
    """打印版本号。"""
    console.print(f"skylens {__version__}")


@app.command
def sources() -> None:
    """列出数据源、授权形态与本地是否已配置 key。"""
    settings = get_settings()
    rows = [
        ("Open-Meteo", "多模式/ensemble 离散度", "免密钥", True),
        ("和风天气", "中国区要素、格点、预警", "需 key", settings.qweather_key is not None),
        ("METAR", "最近机场实况", "免密钥", True),
        ("JMA / 中央气象台", "地面与高空天气图", "须署名", True),
        ("NASA GIBS", "云图瓦片", "免费署名", True),
        ("天地图", "底图（已审图）", "需 key", bool(settings.tianditu_key)),
        ("NOAA CPC", "ONI / SOI", "公有领域", True),
    ]
    table = Table(title="数据源", header_style="bold")
    table.add_column("源")
    table.add_column("用途")
    table.add_column("授权")
    table.add_column("本地状态")
    for name, usage, license_, ready in rows:
        state = "[green]就绪[/green]" if ready else "[yellow]缺 key[/yellow]"
        table.add_row(name, usage, license_, state)
    console.print(table)
    console.print(f"[dim]缓存目录：{settings.cache_dir}[/dim]")


@app.command
def configure(
    llm_api_key: Annotated[
        str | None, Parameter(name=["--llm-api-key"], help="DeepSeek/Qwen API key")
    ] = None,
    qweather_key: Annotated[str | None, Parameter(name=["--qweather-key"])] = None,
    tianditu_key: Annotated[str | None, Parameter(name=["--tianditu-key"])] = None,
) -> None:
    """把密钥写进 .env（权限 0600，已被 .gitignore 排除）。不给参数则交互式询问。"""
    key = llm_api_key or Prompt.ask("LLM API key", password=True, default="")
    written = []
    if key:
        written.append(save_secret_to_env("LLM_API_KEY", key).name)
    if qweather_key:
        written.append(save_secret_to_env("QWEATHER_KEY", qweather_key).name)
    if tianditu_key:
        written.append(save_secret_to_env("TIANDITU_KEY", tianditu_key).name)
    if not written:
        console.print("[yellow]未写入任何密钥[/yellow]")
        return
    console.print(f"[green]已写入[/green] {', '.join(dict.fromkeys(written))}")


def main() -> int:
    """console_scripts 入口。"""
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
