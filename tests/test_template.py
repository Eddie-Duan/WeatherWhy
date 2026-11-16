"""模板降级测试：事实必须来自 fact_pack，且引用全部可解析。"""

from __future__ import annotations

from skylens.core import template, validate


class TestTemplateRender:
    def test_shape_matches_answer_contract(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)

        assert validate.missing_keys(answer) == []
        assert answer["degraded"] is True
        assert answer["inference"]["basis"] == []
        assert "未生成成因推断" in answer["inference"]["text"]

    def test_every_ref_resolves(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)
        validate.assert_refs_resolvable(answer, sample_pack)
        assert answer["facts"], "至少应罗列几条事实"

    def test_values_come_from_pack(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)
        values = {fact["label"]: fact["value"] for fact in answer["facts"]}

        assert values["本地实况（和风格点）"] == "-7.2 °C"
        assert values["机场站点观测"] == "10 °C"
        assert values["海拔订正后气温（推断）"] == "1.5 °C"
        assert values["500hPa 高度"] == "5503 m"

    def test_low_representativeness_is_stated(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)
        assert "代表性 低" in answer["observed"]

    def test_missing_list_is_carried_over(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)
        assert answer["not_covered"] == sample_pack["provenance"]["missing"]

    def test_citations_deduplicated_and_from_pack(self, sample_pack: dict) -> None:
        answer = template.render(sample_pack)
        assert answer["citations"][0] == sample_pack["observed"]["source_url"]
        assert len(answer["citations"]) == len(set(answer["citations"]))

    def test_no_observed_does_not_crash(self, sample_pack: dict) -> None:
        sample_pack["observed"] = {"available": False, "error": "无站点"}
        answer = template.render(sample_pack)

        assert "没有可用观测" in answer["observed"]
        assert "缺" in answer["uncertainty"]

    def test_no_forecast_does_not_crash(self, sample_pack: dict) -> None:
        sample_pack["forecast"] = None
        answer = template.render(sample_pack)
        assert "没有可用预报" in answer["forecast"]

    def test_warnings_are_carried_into_fallback(self, sample_pack: dict) -> None:
        sample_pack["warnings"] = [
            {
                "title": "暴雪蓝色预警",
                "issuer": "正镶白旗气象台",
                "issued_at": "2026-11-15T18:15:00+08:00",
                "text": "原文……",
            }
        ]
        answer = template.render(sample_pack)

        assert "官方预警 1 条" in answer["observed"]
        assert "正镶白旗气象台" in answer["observed"]
        assert "官方预警" in answer["advice"]
