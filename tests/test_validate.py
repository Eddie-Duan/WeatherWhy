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

    def test_dotted_index_is_also_accepted(self) -> None:
        """模型常写 daily.0.temp_max，实测必须容忍，否则会白白降级。"""
        ok, value = validate.resolve_ref(PACK, "forecast.daily.0.temp_max.mean")
        assert ok is True
        assert value == 1.2

    def test_dotted_index_out_of_range(self) -> None:
        assert validate.resolve_ref(PACK, "forecast.daily.7.temp_max.mean")[0] is False

    @pytest.mark.parametrize(
        "ref",
        ["observed.nope", "observed.temp_c.deeper", "forecast.daily[9]", "forecast.daily", "rh"],
    )
    def test_unresolvable_paths(self, ref: str) -> None:
        assert validate.resolve_ref(PACK, ref)[0] is False

    def test_container_allowed_for_basis_but_not_facts(self) -> None:
        # 「依据：synoptic.pattern」是合法证据引用
        assert validate.resolve_ref(PACK, "synoptic", allow_container=True)[0] is True
        assert validate.resolve_ref(PACK, "synoptic")[0] is False

        answer = {
            **GOOD_ANSWER,
            "inference": {"text": "...", "confidence": "中", "basis": ["synoptic"]},
        }
        validate.assert_refs_resolvable(answer, PACK)

        broken = {
            **GOOD_ANSWER,
            "facts": [{"label": "环流", "value": "x", "ref": "synoptic"}],
        }
        with pytest.raises(AssertionError):
            validate.assert_refs_resolvable(broken, PACK)

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


class TestAnswerInvariants:
    """M6 回归集会依赖这组断言，正反两面都要测。"""

    def test_valid_answer_passes(self) -> None:
        pack = {**PACK, "citations": [], "warnings": []}
        answer = {**GOOD_ANSWER, "citations": ["https://example.invalid/x"], "degraded": False}
        pack["observed"]["representativeness"] = {"level": "高", "reason": "近"}
        answer["observed"] = "观测取自近处站点。"
        validate.assert_answer_invariants(answer, pack)

    def test_empty_citations_fail(self) -> None:
        pack = {**PACK, "warnings": []}
        pack["observed"]["representativeness"] = {"level": "高"}
        answer = {**GOOD_ANSWER, "citations": [], "degraded": False}
        with pytest.raises(AssertionError, match="citations"):
            validate.assert_answer_invariants(answer, pack)

    def test_low_representativeness_must_be_declared(self) -> None:
        pack = {**PACK, "warnings": []}
        pack["observed"]["representativeness"] = {"level": "低", "reason": "281 km"}
        answer = {**GOOD_ANSWER, "citations": ["u"], "degraded": False}
        answer["observed"] = "气温 -3.2 °C。"

        with pytest.raises(AssertionError, match="代表性"):
            validate.assert_answer_invariants(answer, pack)

        answer["observed"] = "观测代表性低：距 281 km。"
        validate.assert_answer_invariants(answer, pack)

    def test_warnings_must_be_mentioned(self) -> None:
        pack = {
            **PACK,
            "warnings": [{"title": "大风蓝色预警信号", "text": "原文"}],
            "citations": [],
        }
        pack["observed"]["representativeness"] = {"level": "高"}
        answer = {**GOOD_ANSWER, "citations": ["u"], "degraded": False}
        answer["observed"] = "气温 -3.2 °C。"

        with pytest.raises(AssertionError, match="预警"):
            validate.assert_answer_invariants(answer, pack)

        answer["advice"] = "注意查看官方预警。"
        validate.assert_answer_invariants(answer, pack)

    def test_degraded_answer_needs_reason_and_not_covered(self) -> None:
        pack = {**PACK, "warnings": []}
        pack["observed"]["representativeness"] = {"level": "高"}
        answer = {
            **GOOD_ANSWER,
            "citations": ["u"],
            "degraded": True,
            "fallback_reason": "TimeoutError",
            "not_covered": ["官方预警（未接入）"],
        }
        validate.assert_answer_invariants(answer, pack)

        broken = {**answer, "not_covered": []}
        with pytest.raises(AssertionError, match="not_covered"):
            validate.assert_answer_invariants(broken, pack)

    def test_degraded_disallowed_when_strict(self) -> None:
        pack = {**PACK, "warnings": []}
        pack["observed"]["representativeness"] = {"level": "高"}
        answer = {
            **GOOD_ANSWER,
            "citations": ["u"],
            "degraded": True,
            "fallback_reason": "x",
            "not_covered": ["y"],
        }
        with pytest.raises(AssertionError, match="降级"):
            validate.assert_answer_invariants(answer, pack, allow_degraded=False)
