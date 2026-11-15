"""ENSO 测试：ONI 定宽表解析与 ±0.5 相位判据。"""

from __future__ import annotations

import httpx
import pytest
import respx

from skylens.providers import enso

SAMPLE = """ SEAS  YR   TOTAL   ANOM
  JAS 2025  27.60   0.10
  ASO 2025  27.10  -0.40
  SON 2025  26.14  -0.57
  NDJ 2025  25.96  -0.60
  ASO 2026  29.23   2.46
"""


class TestParse:
    def test_takes_last_valid_row(self) -> None:
        latest = enso.parse_oni(SAMPLE)

        assert latest == {"season": "ASO", "year": 2026, "month": "2026-09", "oni": 2.46}

    def test_skips_header_and_garbage(self) -> None:
        text = " SEAS  YR   TOTAL   ANOM\nnot a row\n JJA 2026  29.09   1.80\n"
        assert enso.parse_oni(text)["season"] == "JJA"

    def test_unknown_season_is_skipped(self) -> None:
        assert enso.parse_oni(" XYZ 2026 1.0 0.5\n") is None


class TestPhase:
    @pytest.mark.parametrize(
        ("oni", "expected"),
        [
            (2.46, "El Niño"),
            (0.5, "El Niño"),
            (0.49, "中性"),
            (0.0, "中性"),
            (-0.5, "La Niña"),
            (-2.0, "La Niña"),
        ],
    )
    def test_thresholds(self, oni: float, expected: str) -> None:
        assert enso.phase(oni) == expected


class TestFetchEnso:
    @respx.mock
    async def test_reads_text_endpoint(self) -> None:
        respx.get(enso.ONI_URL).mock(return_value=httpx.Response(200, text=SAMPLE))
        result = await enso.fetch_enso()

        assert result["phase"] == "El Niño"
        assert result["oni"] == 2.46
        assert result["month"] == "2026-09"
        assert result["source"] == "NOAA CPC ONI"

    @respx.mock
    async def test_http_error_becomes_error_dict(self) -> None:
        respx.get(enso.ONI_URL).mock(return_value=httpx.Response(502))
        result = await enso.fetch_enso()

        assert result["error"] == "HTTP 502"
        assert result["provider"] == "enso"
