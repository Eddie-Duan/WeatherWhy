"""引用校验测试：这是 M3 防幻觉的核心，故意删字段必须被抓到。"""

from __future__ import annotations

import re

import pytest

from skylens.core import validate

PACK = {
    "observed": {"temp_c": -3.2, "wind_dir_deg": 320, "rh_pct": None},
    "forecast": {
        "daily": [
            {"date": "2026-11-16", "temp_max": {"mean": 1.2, "spread": 4.4}},
        ]
    },
    "synoptic": {"h500_geopotential_m": 5320},
}

GOOD_ANSWER = {
    "headline": "冷高压控制",
    "facts": [
        {"label": "现在气温", "value": "-3.2 °C", "ref": "observed.temp_c"},
        {"label": "最高气温", "value": "1.2 °C", "ref": "forecast.daily[0].temp_max.mean"},
    ],
    "observed": "...",
    "forecast": "...",
    "inference": {"text": "...", "confidence": "中", "basis": ["synoptic.h500_geopotential_m"]},
    "uncertainty": "...",
    "advice": "...",
    "not_covered": [],
    "citations": [],
}


class TestResolveRef:
    def test_nested_and_indexed_path(self) -> None:
        ok, value = validate.resolve_ref(PACK, "forecast.daily[0].temp_max.mean")
        assert ok is True
        assert value == 1.2

    @pytest.mark.parametrize(
        "ref",
        ["observed.nope", "observed.temp_c.deeper", "forecast.daily[9]", "forecast.daily", "rh"],
    )
    def test_unresolvable_paths(self, ref: str) -> None:
        assert validate.resolve_ref(PACK, ref)[0] is False

    def test_null_field_counts_as_unresolvable(self) -> None:
        """指向 null 等于编造：那里本来没有数据。"""
        assert validate.resolve_ref(PACK, "observed.rh_pct")[0] is False

    def test_empty_ref(self) -> None:
        assert validate.resolve_ref(PACK, "")[0] is False


class TestAssertRefs:
    def test_good_answer_passes(self) -> None:
        validate.assert_refs_resolvable(GOOD_ANSWER, PACK)

    def test_invented_ref_fails_with_path_listed(self) -> None:
        answer = {
            **GOOD_ANSWER,
            "facts": [
                *GOOD_ANSWER["facts"],
                {"label": "编造", "value": "9 °C", "ref": "observed.temp_c_2m"},
            ],
        }
        with pytest.raises(AssertionError, match=re.escape("observed.temp_c_2m")):
            validate.assert_refs_resolvable(answer, PACK)

    def test_bad_basis_fails(self) -> None:
        answer = {
            **GOOD_ANSWER,
            "inference": {"text": "...", "confidence": "高", "basis": ["synoptic.h850"]},
        }
        with pytest.raises(AssertionError):
            validate.assert_refs_resolvable(answer, PACK)

    def test_deleted_field_is_caught(self) -> None:
        trimmed = {"observed": {"wind_dir_deg": 320}}
        with pytest.raises(AssertionError, match="temp_c"):
            validate.assert_refs_resolvable(GOOD_ANSWER, trimmed)


class TestMissingKeys:
    def test_lists_absent_contract_fields(self) -> None:
        assert validate.missing_keys({"headline": "x"})[0] == "facts"

    def test_complete_answer_has_none_missing(self) -> None:
        assert validate.missing_keys(GOOD_ANSWER) == []
