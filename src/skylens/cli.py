"""命令行壳：cyclopts + rich（沿用旧仓用法，语义改写）。

M0：``version`` / ``sources`` / ``configure``（不取数）。
M1：``where``（地理编码候选）、``pack``（打印 fact_pack）。
``explain`` / ``serve`` / ``ask`` 分别落在 M3–M4。

刻意不做的事：把结构化参数拼成一句自然语言再交给模型解析（旧仓反模式，见 MIGRATION §2.7）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from skylens import __version__
from skylens.core.explain import explain as explain_pack
from skylens.core.fact_pack import build_fact_pack
from skylens.doctor import all_critical_ok, run_checks
from skylens.providers.geocode import geocode
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
        ("Nominatim", "中文地名（实测最稳）", "免费，须 UA", True),
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


@app.command
def where(place: str) -> None:
    """只做地理编码：打印候选与置信度，不取天气数据。"""
    settings = get_settings()
    result = asyncio.run(geocode(place, settings=settings))
    if "error" in result:
        console.print(f"[red]地理编码失败[/red]：{result['error']}")
        raise SystemExit(1)

    table = Table(title=f"{place} → {result['name']}", header_style="bold")
    table.add_column("候选")
    table.add_column("行政区")
    table.add_column("纬度", justify="right")
    table.add_column("经度", justify="right")
    table.add_column("得分", justify="right")
    for index, cand in enumerate(result["geocode_candidates"]):
        marker = "→ " if index == 0 else "  "
        table.add_row(
            f"{marker}{cand['name']}",
            cand["admin"],
            f"{cand['lat']:.4f}",
            f"{cand['lon']:.4f}",
            f"{cand['score']:.2f}",
        )
    console.print(table)
    console.print(
        f"[dim]来源 {result['geocode_source']}；"
        f"选定 {result['lat']:.4f}, {result['lon']:.4f}；"
        f"置信度 {result['geocode_confidence']:.2f}[/dim]"
    )


@app.command
def pack(
    place: str,
    days: Annotated[int, Parameter(name=["--days"])] = 7,
    raw: Annotated[bool, Parameter(name=["--raw"], help="打印完整 JSON")] = False,
    out: Annotated[Path | None, Parameter(name=["--out"], help="把 JSON 写到此路径")] = None,
) -> None:
    """组装并打印 fact_pack（确定性，不走 LLM）。"""
    pack_data = asyncio.run(build_fact_pack(place, days=days))
    if "error" in pack_data:
        console.print(f"[red]fact_pack 生成失败[/red]：{pack_data['error']}")
        if pack_data.get("detail"):
            console.print(f"[dim]{pack_data['detail']}[/dim]")
        raise SystemExit(1)

    if out is not None:
        out.write_text(json.dumps(pack_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        console.print(f"[green]已写入[/green] {out}")

    if raw:
        console.print_json(json.dumps(pack_data, ensure_ascii=False))
        return
    _print_pack(pack_data)


@app.command
def explain(
    place: str,
    days: Annotated[int, Parameter(name=["--days"])] = 7,
    raw: Annotated[bool, Parameter(name=["--raw"], help="打印解释 JSON")] = False,
) -> None:
    """组装 fact_pack → 单次 LLM 解释 → 引用校验；失败自动降级为模板版本。"""
    settings = get_settings()

    async def _run() -> tuple[dict, dict | None]:
        pack_data = await build_fact_pack(place, days=days, settings=settings)
        if "error" in pack_data:
            return pack_data, None
        return pack_data, await explain_pack(pack_data, settings=settings)

    pack_data, answer = asyncio.run(_run())
    if answer is None:
        console.print(f"[red]fact_pack 生成失败[/red]：{pack_data.get('error')}")
        raise SystemExit(1)

    if raw:
        console.print_json(json.dumps(answer, ensure_ascii=False))
        return
    _print_answer(answer, pack_data)


@app.command
def doctor(
    no_llm: Annotated[bool, Parameter(name=["--no-llm"], help="跳过 LLM 连通性检查")] = False,
) -> None:
    """检查环境、密钥、LLM 与各数据源是否可用。"""
    checks = asyncio.run(run_checks(get_settings(), check_llm=not no_llm))
    table = Table(title="skylens doctor", header_style="bold")
    table.add_column("检查")
    table.add_column("结果")
    table.add_column("详情")
    table.add_column("耗时", justify="right")
    for check in checks:
        mark = "[green]OK[/green]" if check.ok else "[red]FAIL[/red]"
        table.add_row(check.name, mark, check.detail, f"{check.latency_ms} ms")
    console.print(table)
    if not all_critical_ok(checks):
        console.print("[red]关键检查未通过[/red]（Python / 密钥 / 缓存目录 / LLM 连通）")
        raise SystemExit(1)


def _print_answer(answer: dict, pack_data: dict) -> None:
    location = pack_data["location"]
    console.rule(f"{location['name']} · {location['admin']}")
    console.print(f"[bold]{answer.get('headline', '')}[/bold]")
    if answer.get("degraded"):
        console.print(
            "[yellow]本次未生成解释（降级为事实罗列）[/yellow]："
            + str(answer.get("fallback_reason", ""))[:200]
        )

    facts = answer.get("facts") or []
    if facts:
        table = Table(header_style="bold", show_edge=False)
        table.add_column("事实")
        table.add_column("值")
        table.add_column("引用", style="dim")
        for fact in facts:
            table.add_row(
                str(fact.get("label", "")), str(fact.get("value", "")), str(fact.get("ref", ""))
            )
        console.print(table)

    sections = (
        ("观测", answer.get("observed")),
        ("预报", answer.get("forecast")),
        ("不确定性", answer.get("uncertainty")),
        ("建议", answer.get("advice")),
    )
    for title, text in sections:
        if text:
            console.print(f"[cyan]{title}[/cyan] {text}")

    inference = answer.get("inference") or {}
    if inference.get("text"):
        basis = "、".join(inference.get("basis") or []) or "无"
        console.print(
            f"[magenta]推断[/magenta]（置信度 {inference.get('confidence', '缺')}）"
            f"{inference['text']}\n[dim]依据：{basis}[/dim]"
        )

    not_covered = answer.get("not_covered") or []
    if not_covered:
        console.print(f"[dim]未覆盖：{'；'.join(str(item) for item in not_covered)}[/dim]")

    citations = answer.get("citations") or []
    if citations:
        console.print("[dim]引用：" + "  ".join(str(url) for url in citations[:6]) + "[/dim]")


def _print_pack(data: dict) -> None:
    location = data["location"]
    console.rule(f"{location['name']} · {location['admin']}")
    console.print(
        f"[dim]{location['lat']:.4f}, {location['lon']:.4f}"
        f"｜海拔 {_g(location.get('elevation_m'))} m"
        f"｜地理编码 {location['geocode_source']}"
        f"（{location['geocode_confidence']:.2f}）[/dim]"
    )
    console.print(f"[dim]fact_pack_id {data['fact_pack_id']}[/dim]")

    observed = data["observed"]
    if observed.get("available"):
        rep = observed["representativeness"]
        console.print(
            f"[yellow]观测[/yellow] {observed['valid_time']}（{observed['age_minutes']} 分钟前）"
        )
        console.print(
            f"  {_g(observed['temp_c'])} °C  露点 {_g(observed['dewpoint_c'])} °C"
            f"  湿度 {_g(observed['rh_pct'])}%  气压 {_g(observed['pressure_msl_hpa'])} hPa"
        )
        console.print(
            f"  风 {_g(observed['wind_dir_deg'])}° {_g(observed['wind_speed_ms'])} m/s"
            f"（阵风 {_g(observed['wind_gust_ms'])}）"
            f"  能见度 {_g(observed['visibility_m'])} m  现象 {observed['weather_code'] or '—'}"
        )
        console.print(
            f"  站点 {observed['station']['id']} {observed['station']['name']}"
            f"｜代表性 [bold]{rep['level']}[/bold]：{rep['reason']}"
        )
    else:
        console.print(f"[red]无可用观测[/red]：{observed.get('error')}")

    forecast = data.get("forecast")
    if forecast:
        table = Table(title=f"多模式预报（{len(forecast['models'])} 个模式）", header_style="bold")
        for column in ("日期", "最高 °C", "最低 °C", "降水 mm", "最大风 m/s"):
            table.add_column(column, justify="right")
        for day in forecast["daily"][:7]:
            table.add_row(
                day["date"],
                _fmt(day["temp_max"]),
                _fmt(day["temp_min"]),
                _fmt(day["precip_mm"]),
                _fmt(day["wind_max_ms"]),
            )
        console.print(table)
        agreement = forecast.get("agreement", {})
        console.print(
            "  "
            + "  ".join(f"{name} {info['level']}" for name, info in agreement.items())
            + "  [dim]（离散度越小越一致）[/dim]"
        )
    else:
        console.print("[red]无预报数据[/red]")

    synoptic = data.get("synoptic") or {}
    if synoptic.get("h500_geopotential_m") is not None or synoptic.get("charts"):
        pattern = synoptic.get("pattern") or {}
        console.print(
            f"[magenta]环流[/magenta] 500hPa {_g(synoptic.get('h500_geopotential_m'))} m"
            f"｜850hPa {_g(synoptic.get('t850_c'))} °C"
            f" {_g(synoptic.get('wind850_dir_deg'))}° {_g(synoptic.get('wind850_speed_ms'))} m/s"
            f"｜型：{pattern.get('label', '缺')}"
        )
        console.print(
            f"  天气图 {len(synoptic.get('charts') or [])} 张"
            f"（{synoptic.get('valid_time') or '时刻缺'}）"
        )

    climate = data.get("climate") or {}
    if climate:
        enso = climate.get("enso") or {}
        console.print(
            f"[magenta]气候[/magenta] {climate.get('season', '缺')}"
            f"｜ENSO {enso.get('phase', '缺')}"
            f"（ONI {_g(enso.get('oni'), 2)}，{enso.get('month', '缺')}）"
        )

    console.print(f"[dim]缺失：{'；'.join(data['provenance']['missing'])}[/dim]")


def _fmt(block: dict) -> str:
    mean, spread = block.get("mean"), block.get("spread")
    if mean is None:
        return "—"
    return f"{_g(mean)}±{_g(spread)}" if spread is not None else _g(mean)


def _g(value: float | int | None, digits: int = 1) -> str:
    """数字显示：整数去掉 ``.0``，其余按 ``digits`` 位小数。"""
    if value is None:
        return "—"
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{digits}f}"


def main() -> int:
    """console_scripts 入口。"""
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
