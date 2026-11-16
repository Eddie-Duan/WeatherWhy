"""快照存档测试：落盘、去重、读取、列表。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skylens.core import archive


def _pack(fact_pack_id: str = "sha256:abc123", place: str = "明安图镇") -> dict:
    return {
        "schema_version": "1.0",
        "fact_pack_id": fact_pack_id,
        "generated_at": "2026-11-15T17:00:00+08:00",
        "location": {"name": place},
        "observed": {"available": True},
        "warnings": [],
        "provenance": {"missing": [], "notes": []},
    }


class TestSaveLoad:
    def test_roundtrip(self, tmp_path: Path) -> None:
        path = archive.save_pack(_pack(), root=tmp_path)
        loaded = archive.load_pack("sha256:abc123", root=tmp_path)

        assert path.name == "abc123.json"
        assert loaded["fact_pack_id"] == "sha256:abc123"
        assert loaded["location"]["name"] == "明安图镇"

    def test_same_id_written_once(self, tmp_path: Path) -> None:
        first = archive.save_pack(_pack(), root=tmp_path)
        mtime = first.stat().st_mtime
        second = archive.save_pack(_pack(), root=tmp_path)

        assert first == second
        assert second.stat().st_mtime == mtime

    def test_pack_without_id_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="fact_pack_id"):
            archive.save_pack({"location": {}}, root=tmp_path)

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            archive.load_pack("sha256:nope", root=tmp_path)


class TestList:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert archive.list_packs(root=tmp_path) == []

    def test_lists_summaries(self, tmp_path: Path) -> None:
        archive.save_pack(_pack("sha256:aaa", "明安图镇"), root=tmp_path)
        items = archive.list_packs(root=tmp_path)

        assert len(items) == 1
        assert items[0]["place"] == "明安图镇"
        assert items[0]["fact_pack_id"] == "sha256:aaa"
        assert items[0]["size_bytes"] > 0

    def test_ignores_corrupt_files(self, tmp_path: Path) -> None:
        archive.save_pack(_pack(), root=tmp_path)
        (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

        items = archive.list_packs(root=tmp_path)
        assert [item["fact_pack_id"] for item in items] == ["sha256:abc123"]

    def test_json_is_readable_utf8(self, tmp_path: Path) -> None:
        path = archive.save_pack(_pack(), root=tmp_path)
        text = path.read_text(encoding="utf-8")
        assert "明安图镇" in json.loads(text)["location"]["name"]
