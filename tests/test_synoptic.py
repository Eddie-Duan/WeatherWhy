"""环流型判定与季节文案测试：规则必须可解释，且 basis 指回真实路径。"""

from __future__ import annotations

from skylens.core import synoptic, vocab


class TestClassifyPattern:
    def test_deep_trough_with_northwest_flow(self) -> None:
        pattern = synoptic.classify_pattern(
            {
                "h500_geopotential_m": 5320.0,
                "t850_c": -12.0,
                "wind850_dir_deg": 300.0,
                "wind850_speed_ms": 14.0,
            }
        )

        assert "500hPa 深槽控制" in pattern["label"]
        assert "850hPa 西北气流" in pattern["label"]
        assert "低层冷平流明显" in pattern["label"]
        assert pattern["confidence"] == "推断"
        assert pattern["basis"] == [
            "synoptic.h500_geopotential_m",
            "synoptic.wind850_dir_deg",
            "synoptic.t850_c",
            "synoptic.wind850_speed_ms",
        ]

    def test_ridge_and_warm_layer(self) -> None:
        pattern = synoptic.classify_pattern(
            {"h500_geopotential_m": 5700.0, "t850_c": 8.0, "wind850_dir_deg": 225.0}
        )

        assert "高压脊控制" in pattern["label"]
        assert "西南气流" in pattern["label"]
        assert "冷平流" not in pattern["label"]

    def test_flat_westerlies_band(self) -> None:
        pattern = synoptic.classify_pattern({"h500_geopotential_m": 5500.0})
        assert "平直西风" in pattern["label"]

    def test_missing_data_is_admitted_not_invented(self) -> None:
        pattern = synoptic.classify_pattern({})

        assert "资料缺失" in pattern["label"]
        assert pattern["basis"] == []

    def test_no_basis_for_absent_fields(self) -> None:
        pattern = synoptic.classify_pattern({"h500_geopotential_m": 5400.0})
        assert pattern["basis"] == ["synoptic.h500_geopotential_m"]


class TestBuildSynoptic:
    def test_passes_charts_through_and_leaves_anomaly_null(self) -> None:
        pressure = {
            "h500_geopotential_m": 5320.0,
            "t850_c": -8.0,
            "wind850_dir_deg": 300.0,
            "wind850_speed_ms": 14.0,
            "valid_time": "2026-11-15T17:00+08:00",
            "source_url": "https://example.invalid/pl",
        }
        charts = [{"title": "JMA", "url": "https://example.invalid/chart.png"}]
        result = synoptic.build_synoptic(pressure, charts)

        assert result["charts"] == charts
        assert result["h500_anomaly_m"] is None
        assert result["valid_time"] == "2026-11-15T17:00+08:00"
        assert result["pattern"]["label"]

    def test_empty_pressure_still_returns_block(self) -> None:
        result = synoptic.build_synoptic({}, [])
        assert result["h500_geopotential_m"] is None
        assert "资料缺失" in result["pattern"]["label"]


class TestSeasonLabel:
    def test_november_is_early_winter(self) -> None:
        assert vocab.season_label(11) == "初冬"
        assert vocab.season_label(7) == "盛夏"
        assert vocab.season_label(12) == "隆冬"
        assert vocab.season_label(1) == "隆冬"
