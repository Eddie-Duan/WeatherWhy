"""集合统计算法测试 —— 用例从旧仓语义反推，重点在「离散度 = p90 - p10」。"""

from __future__ import annotations

import math

import pytest

from skylens.core import stats


def _member(model: str, temp_max: list[float], temp_min: list[float] | None = None) -> dict:
    daily = {"temp_max": temp_max}
    if temp_min is not None:
        daily["temp_min"] = temp_min
    return {"model": model, "daily": daily}


class TestEnsembleStatistics:
    def test_five_members_matches_hand_computed_percentiles(self) -> None:
        members = [_member(f"m{i}", [float(i)]) for i in range(5)]
        result = stats.calculate_ensemble_statistics(
            members, "temp_max", kind="daily", use_max=True
        )

        assert result["mean"] == 2.0
        assert result["p10"] == 0.4  # numpy 线性插值
        assert result["p90"] == 3.6
        assert result["spread"] == 3.2

    def test_use_max_and_use_min_pick_opposite_ends(self) -> None:
        members = [_member("a", [1.0, 9.0]), _member("b", [3.0, 5.0])]

        with_max = stats.calculate_ensemble_statistics(members, "temp_max", use_max=True)
        with_min = stats.calculate_ensemble_statistics(members, "temp_max", use_max=False)

        assert with_max["mean"] == 7.0  # max(1,9)=9 与 max(3,5)=5 的均值
        assert with_min["mean"] == 2.0  # min(1,9)=1 与 min(3,5)=3 的均值

    def test_nan_values_are_dropped_not_used_as_zero(self) -> None:
        members = [_member("a", [1.0, math.nan]), _member("b", [3.0, math.nan])]
        result = stats.calculate_ensemble_statistics(members, "temp_max", use_max=True)
        assert result["mean"] == 2.0

    def test_empty_input_returns_nan_not_exception(self) -> None:
        result = stats.calculate_ensemble_statistics([], "temp_max", use_max=True)
        assert math.isnan(result["mean"])
        assert math.isnan(result["spread"])

    def test_missing_variable_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="缺少变量"):
            stats.extract_variable_data(_member("a", [1.0]), "temp_min", kind="daily")

    def test_unknown_kind_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="kind 只能是"):
            stats.extract_variable_data(_member("a", [1.0]), "temp_max", kind="monthly")  # type: ignore[arg-type]

    def test_hourly_kind_reads_hourly_block(self) -> None:
        record = {"model": "a", "hourly": {"temperature_2m": [1.0, 2.0, 3.0]}}
        values = stats.extract_variable_data(record, "temperature_2m", kind="hourly")
        assert values.tolist() == [1.0, 2.0, 3.0]


class TestModelAgreement:
    @pytest.mark.parametrize(
        ("variable", "spread", "expected"),
        [
            ("temperature", 2.9, "高"),
            ("temperature", 4.4, "中"),
            ("temperature", 7.0, "低"),
            ("precipitation", 0.4, "高"),
            ("wind", 3.0, "中"),
            ("wind", 11.0, "低"),
        ],
    )
    def test_thresholds_carry_over_from_old_repo(
        self, variable: str, spread: float, expected: str
    ) -> None:
        assert stats.calculate_model_agreement(spread, variable)["level"] == expected

    def test_accepts_member_values_and_computes_spread(self) -> None:
        result = stats.calculate_model_agreement([0.0, 2.0, 4.0], "temperature")
        assert result["spread"] == pytest.approx(3.2, abs=0.01)


class TestForecastUncertainty:
    def test_maps_daily_blocks_onto_fact_pack_agreement(self) -> None:
        daily = [
            {
                "temp_max": {"mean": 1.2, "p10": -1.0, "p90": 3.4, "spread": 4.4},
                "temp_min": {"mean": -11.5, "p10": -14.2, "p90": -9.0, "spread": 5.2},
                "precip_mm": {"mean": 0.0, "p90": 0.4, "spread": 0.4},
                "wind_max_ms": {"mean": 11.0, "p90": 14.0, "spread": 3.0},
            }
        ]
        agreement = stats.summarize_forecast_uncertainty(daily, basis="Open-Meteo ensemble")

        assert agreement["temperature_max"]["level"] == "中"
        assert agreement["precipitation"]["level"] == "高"
        assert agreement["wind"]["level"] == "中"
        assert agreement["temperature_max"]["basis"] == "Open-Meteo ensemble"

    def test_takes_worst_day_across_days(self) -> None:
        daily = [
            {"temp_max": {"spread": 1.0}},
            {"temp_max": {"spread": 9.0}},
        ]
        assert stats.summarize_forecast_uncertainty(daily)["temperature_max"]["level"] == "低"

    def test_skips_fields_without_spread(self) -> None:
        assert stats.summarize_forecast_uncertainty([{"wind_max_ms": {"mean": 3.0}}]) == {}


class TestDailyRange:
    def test_range_statistics(self) -> None:
        daily = [
            {"temp_max": {"mean": 1.0}, "temp_min": {"mean": -9.0}},
            {"temp_max": {"mean": 2.0}, "temp_min": {"mean": -8.0}},
        ]
        result = stats.calculate_daily_temperature_range_statistics(daily)
        assert result == {"mean": 10.0, "min": 10.0, "max": 10.0, "n": 2}

    def test_empty_input(self) -> None:
        assert stats.calculate_daily_temperature_range_statistics([])["n"] == 0
