"""单位换算测试：旧仓把英制写死在请求参数里，这里守住公制收敛点。"""

from __future__ import annotations

import pytest

from skylens.core import units, vocab


class TestUnits:
    def test_temperature(self) -> None:
        assert units.f_to_c(32.0) == 0.0
        assert units.f_to_c(-40.0) == -40.0
        assert units.c_to_f(0.0) == 32.0

    def test_wind_speed_to_ms(self) -> None:
        assert units.mph_to_ms(10.0) == pytest.approx(4.4704)
        assert units.knots_to_ms(10.0) == pytest.approx(5.14444)
        assert units.kmh_to_ms(36.0) == pytest.approx(10.0)
        assert units.wind_speed_to_ms(10.0, "KT") == pytest.approx(5.14444)
        assert units.wind_speed_to_ms(2.0, "m/s") == 2.0

    def test_unknown_wind_unit(self) -> None:
        with pytest.raises(ValueError, match="未知风速单位"):
            units.wind_speed_to_ms(1.0, "furlong/fortnight")

    def test_pressure_and_distance(self) -> None:
        assert units.inhg_to_hpa(29.92) == pytest.approx(1013.2, abs=0.1)
        assert units.ft_to_m(1010.0) == pytest.approx(307.848)
        assert units.mile_to_m(1.0) == pytest.approx(1609.344)
        assert units.inch_to_mm(1.0) == 25.4

    def test_missing_stays_none(self) -> None:
        assert units.round_or_none(None) is None
        assert units.round_or_none(1.234, 1) == 1.2


class TestVocab:
    def test_wind_direction_label(self) -> None:
        assert vocab.wind_direction_label(0) == "北"
        assert vocab.wind_direction_label(320) == "西北"
        assert vocab.wind_direction_label(359) == "北"
        assert vocab.wind_direction_label(None) is None

    def test_confidence_levels_match_design(self) -> None:
        assert vocab.CONFIDENCE_LEVELS == ("低", "中", "高")
        assert vocab.EVIDENCE_KINDS == ("观测", "预报", "推断")
