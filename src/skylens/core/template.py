"""模板降级：LLM 不可用或输出没通过校验时，只罗列事实、不做成因推断。

原则是「宁可少说，不可乱说」：这里产出的每个数值都直接来自 fact_pack，
且带 ``degraded: true``，前端必须据此提示「本次未生成解释」。
"""

from __future__ import annotations

from typing import Any

from skylens.core import vocab
from skylens.core.validate import resolve_ref


def _value(pack: dict[str, Any], ref: str) -> Any | None:
    ok, value = resolve_ref(pack, ref)
    return value if ok else None


def _num(value: Any, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "缺"
    if isinstance(value, float):
        text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
        return f"{text} {unit}".strip()
    return f"{value} {unit}".strip()


def _facts(pack: dict[str, Any]) -> list[dict[str, str]]:
    observed = pack.get("observed") or {}
    daily = ((pack.get("forecast") or {}).get("daily") or [{}])[0]
    synoptic = pack.get("synoptic") or {}
    candidates = [
        (
            "本地实况（和风格点）",
            "observed.local.temp_c",
            _num((observed.get("local") or {}).get("temp_c"), "°C"),
        ),
        ("机场站点观测", "observed.temp_c", _num(observed.get("temp_c"), "°C")),
        (
            "体感温度（自算）",
            "derived.wind_chill_c.value",
            _num(((pack.get("derived") or {}).get("wind_chill_c") or {}).get("value"), "°C"),
        ),
        (
            "海拔订正后气温（推断）",
            "observed.temp_adjusted.temp_c",
            _num((observed.get("temp_adjusted") or {}).get("temp_c"), "°C"),
        ),
        ("露点", "observed.dewpoint_c", _num(observed.get("dewpoint_c"), "°C")),
        ("海平面气压", "observed.pressure_msl_hpa", _num(observed.get("pressure_msl_hpa"), "hPa")),
        (
            "风",
            "observed.wind_speed_ms",
            f"{_num(observed.get('wind_speed_ms'), 'm/s')} "
            f"（{vocab.wind_direction_label(observed.get('wind_dir_deg')) or '风向缺'}）",
        ),
        (
            "今日最高气温",
            "forecast.daily[0].temp_max.mean",
            _num((daily.get("temp_max") or {}).get("mean"), "°C"),
        ),
        (
            "今日最低气温",
            "forecast.daily[0].temp_min.mean",
            _num((daily.get("temp_min") or {}).get("mean"), "°C"),
        ),
        (
            "500hPa 高度",
            "synoptic.h500_geopotential_m",
            _num(synoptic.get("h500_geopotential_m"), "m", 0),
        ),
        ("850hPa 气温", "synoptic.t850_c", _num(synoptic.get("t850_c"), "°C")),
    ]
    return [
        {"label": label, "value": value, "ref": ref}
        for label, ref, value in candidates
        if value != "缺" and _value(pack, ref) is not None
    ]


def _agreement_text(pack: dict[str, Any]) -> str:
    agreement = (pack.get("forecast") or {}).get("agreement") or {}
    names = {
        "temperature_max": "最高气温",
        "temperature_min": "最低气温",
        "precipitation": "降水",
        "wind": "风",
    }
    parts = [f"{names.get(key, key)}{value['level']}" for key, value in agreement.items()]
    return "、".join(parts) if parts else "缺"


def render(pack: dict[str, Any]) -> dict[str, Any]:
    observed = pack.get("observed") or {}
    station = observed.get("station") or {}
    reps = observed.get("representativeness") or {}
    location = pack.get("location") or {}

    warnings = pack.get("warnings") or []
    warnings_text = (
        "官方预警 "
        + str(len(warnings))
        + " 条（原文照搬）："
        + "；".join(
            f"{item.get('title')}（{item.get('issuer')} {item.get('issued_at')}）"
            for item in warnings
        )
        if warnings
        else ""
    )

    observed_text = (
        f"观测取自 {station.get('id', '缺')}（{station.get('name', '缺')}，"
        f"{station.get('distance_km', '缺')} km 外），有效时刻 {observed.get('valid_time', '缺')}。"
        f"代表性 {reps.get('level', '缺')}：{reps.get('reason', '缺')}"
        if observed.get("available")
        else "本次没有可用观测（附近无 METAR 报）。"
    )

    forecast = pack.get("forecast")
    if forecast:
        daily = (forecast.get("daily") or [{}])[0]
        temp_max = daily.get("temp_max") or {}
        forecast_text = (
            f"{len(forecast.get('models') or [])} 个模式对 {daily.get('date', '明日')} 的最高气温："
            f"{_num(temp_max.get('mean'), '°C')}"
            f"（p10–p90 {_num(temp_max.get('p10'), '°C')} ~ {_num(temp_max.get('p90'), '°C')}，"
            f"差 {_num(temp_max.get('spread'), '°C')}）。要素一致性：{_agreement_text(pack)}。"
        )
    else:
        forecast_text = "本次没有可用预报。"

    citations = [
        url
        for url in (
            observed.get("source_url"),
            (pack.get("synoptic") or {}).get("source_url"),
            *[
                chart.get("url")
                for chart in ((pack.get("synoptic") or {}).get("charts") or [])
                if chart.get("url")
            ],
        )
        if url
    ]

    return {
        "headline": f"{location.get('name', '该地')}：本次仅罗列事实，未生成成因解释",
        "facts": _facts(pack),
        "observed": (observed_text + ("\n" + warnings_text if warnings_text else "")),
        "forecast": forecast_text,
        "inference": {
            "text": (
                "本次未生成成因推断（LLM 不可用或输出未通过校验）。上列为确定性代码组装的事实。"
            ),
            "confidence": "低",
            "basis": [],
        },
        "uncertainty": (
            f"要素一致性：{_agreement_text(pack)}；观测代表性 {reps.get('level', '缺')}。"
        ),
        "advice": (
            ("请先阅读上方官方预警原文，并以官方发布为准。\n" if warnings else "")
            + "不做生活建议——结论尚未生成，请以官方发布与原始数据为准。"
        ),
        "not_covered": list((pack.get("provenance") or {}).get("missing") or []),
        "citations": list(dict.fromkeys(citations)),
        "degraded": True,
    }
