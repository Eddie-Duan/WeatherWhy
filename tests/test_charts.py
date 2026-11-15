"""天气图测试：JMA list.json 解析、时间换算、中央气象台外链。"""

from __future__ import annotations

from skylens.providers import charts

ASIA_NOW = [
    "20261115024001_0_Z__C_010000_20261115000000_MET_CHT_JCIasas_JCP600x512_JRcolor_Tjmahp_image.png",
    "20261115084001_0_Z__C_010000_20261115060000_MET_CHT_JCIasas_JCP600x512_JRcolor_Tjmahp_image.png",
]
PAYLOAD = {
    "near": {"now": [], "ft24": [], "ft48": []},
    "asia": {
        "now": ASIA_NOW,
        "ft24": [
            "20261115052700_0_Z__C_010000_20261115000000_MET_CHT_JCIfsas24_JCP600x512_JRcolor.png"
        ],
        "ft48": [
            "20261115073900_0_Z__C_010000_20261115000000_MET_CHT_JCIfsas48_JCP600x512_JRcolor.png"
        ],
    },
}


class TestFilenameTime:
    def test_parses_utc_stamp(self) -> None:
        moment = charts.filename_time(ASIA_NOW[1])
        assert moment is not None
        assert moment.isoformat() == "2026-11-15T06:00:00+00:00"

    def test_unparseable_returns_none(self) -> None:
        assert charts.filename_time("no-time-here.png") is None


class TestBuildCharts:
    def test_picks_latest_now_and_both_forecasts(self) -> None:
        result = charts.build_charts(PAYLOAD)
        jma = [item for item in result if item["url"].startswith(charts.JMA_PNG_BASE)]

        assert len(jma) == 3
        assert jma[0]["title"] == "JMA 亚洲地面天气图（实况）"
        assert jma[0]["url"].endswith(ASIA_NOW[1])  # 取最新一条
        assert jma[0]["valid_time"] == "2026-11-15T14:00:00+08:00"
        assert jma[0]["license"] == charts.JMA_LICENSE
        assert [item["title"] for item in jma[1:]] == [
            "JMA 亚洲地面天气图（24 小时予想）",
            "JMA 亚洲地面天气图（48 小时予想）",
        ]

    def test_appends_nmc_links(self) -> None:
        result = charts.build_charts(PAYLOAD)
        nmc = [item for item in result if item["url"].startswith("http://www.nmc.cn/")]

        assert len(nmc) == len(charts.NMC_PAGES)
        assert all(item["license"] == charts.NMC_LICENSE for item in nmc)

    def test_empty_payload_yields_nothing(self) -> None:
        assert charts.build_charts({}) == []
