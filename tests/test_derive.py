"""海拔订正测试：只在条件充分时给结果，且永远标注为「推断」。"""

from __future__ import annotations

from skylens.core import derive


class TestAdjustTemperature:
    def test_cools_air_up_the_mountain(self) -> None:
        result = derive.adjust_temperature_to_elevation(10.0, 31.0, 1345.0)

        assert result is not None
        assert result["elevation_delta_m"] == 1314
        # 10 - 6.5 * 1.314 = 1.46 → 1.5
        assert result["temp_c"] == 1.5
        assert result["observed_station_temp_c"] == 10.0
        assert result["confidence"] == "推断（自算）"

    def test_warming_downhill(self) -> None:
        result = derive.adjust_temperature_to_elevation(-5.0, 1500.0, 500.0)

        assert result is not None
        assert result["elevation_delta_m"] == -1000
        assert result["temp_c"] == 1.5

    def test_small_elevation_difference_is_not_adjusted(self) -> None:
        assert derive.adjust_temperature_to_elevation(10.0, 100.0, 300.0) is None

    def test_missing_inputs_return_none(self) -> None:
        assert derive.adjust_temperature_to_elevation(None, 31.0, 1345.0) is None
        assert derive.adjust_temperature_to_elevation(10.0, None, 1345.0) is None
        assert derive.adjust_temperature_to_elevation(10.0, 31.0, None) is None

    def test_caveats_are_explicit(self) -> None:
        result = derive.adjust_temperature_to_elevation(10.0, 31.0, 1345.0)
        assert result is not None
        joined = "；".join(result["caveats"])
        assert "水平距离" in joined
        assert "不可替代观测" in joined

    def test_custom_lapse_rate(self) -> None:
        result = derive.adjust_temperature_to_elevation(10.0, 0.0, 1000.0, lapse_c_per_km=10.0)
        assert result is not None
        assert result["temp_c"] == 0.0
        assert result["lapse_rate_c_per_km"] == 10.0


class TestWindChill:
    def test_matches_reference_formula(self) -> None:
        # 0 °C、20 km/h → Environment Canada 约 -5.2 °C
        result = derive.wind_chill_c(0.0, 20 / 3.6)
        assert result is not None
        assert result["value"] == -5.2
        assert result["wind_kmh"] == 20.0

    def test_not_applied_when_warm(self) -> None:
        assert derive.wind_chill_c(20.0, 5.0) is None

    def test_not_applied_when_calm(self) -> None:
        assert derive.wind_chill_c(0.0, 0.5) is None

    def test_missing_inputs(self) -> None:
        assert derive.wind_chill_c(None, 3.0) is None
        assert derive.wind_chill_c(0.0, None) is None


class TestDewpointDepression:
    def test_dry_air_label(self) -> None:
        result = derive.dewpoint_depression_c(10.0, -5.0)
        assert result is not None
        assert result["value"] == 15.0
        assert result["label"] == "干燥"

    def test_near_saturation(self) -> None:
        result = derive.dewpoint_depression_c(5.0, 4.0)
        assert result is not None
        assert "饱和" in result["label"]


class TestThickness:
    def test_thickness_and_850_height_are_sane(self) -> None:
        result = derive.thickness_and_lapse_rate(5500.0, -23.0, -7.0)
        assert result is not None
        # 厚度 ~3.9 km，850hPa 高度 ~1.6 km，都是量级正确的
        assert 3800 < result["thickness_500_850_m"] < 4100
        assert 1400 < result["h850_estimated_m"] < 1800
        assert result["unit"] == "°C/km"
        assert "稳定" in result["stability"]

    def test_stable_when_lapse_small(self) -> None:
        result = derive.thickness_and_lapse_rate(5400.0, -20.0, -22.0)
        assert result is not None
        assert "稳定" in result["stability"]

    def test_missing_inputs(self) -> None:
        assert derive.thickness_and_lapse_rate(None, -23.0, -7.0) is None


class TestPressureTendency:
    def test_rising(self) -> None:
        result = derive.pressure_tendency(2.1)
        assert result is not None and "加压" in result["label"]

    def test_falling(self) -> None:
        result = derive.pressure_tendency(-2.0)
        assert result is not None and "减压" in result["label"]

    def test_steady(self) -> None:
        result = derive.pressure_tendency(0.3)
        assert result is not None and "变化不大" in result["label"]

    def test_missing(self) -> None:
        assert derive.pressure_tendency(None) is None
