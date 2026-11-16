"""M6 回归集（离线部分）：回放录制的真实回答，检查它们仍然满足全部硬约束。

录制发生在 ``scripts/run_regression.py --record``；这里只读文件，不调用 LLM、不触网，
所以能在 CI 里跑。真实调用留给 nightly 的 ``--live``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skylens.core import validate

FIXTURES = Path(__file__).parent / "fixtures" / "regression"
QUESTIONS_FILE = FIXTURES / "questions.json"
ANSWERS_DIR = FIXTURES / "answers"
PACKS_DIR = FIXTURES / "packs"


def _recorded() -> list:
    if not ANSWERS_DIR.is_dir():
        return []
    params = []
    for path in sorted(ANSWERS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        pack_file = PACKS_DIR / f"{payload['pack_id'].split(':')[-1]}.json"
        params.append(pytest.param(payload, pack_file, id=payload["id"]))
    return params


class TestQuestionSet:
    def test_ten_questions_over_three_places(self) -> None:
        questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))

        assert len(questions) == 10
        assert {item["place"] for item in questions} == {"明安图镇", "锡林浩特", "二连浩特"}
        assert all(item["question"].strip() for item in questions)
        assert len({item["id"] for item in questions}) == 10


@pytest.mark.parametrize(("payload", "pack_file"), _recorded())
class TestRecordedAnswers:
    def test_answer_still_satisfies_invariants(self, payload: dict, pack_file: Path) -> None:
        pack = json.loads(pack_file.read_text(encoding="utf-8"))
        validate.assert_answer_invariants(payload["answer"], pack)

    def test_pack_snapshot_matches_its_id(self, payload: dict, pack_file: Path) -> None:
        pack = json.loads(pack_file.read_text(encoding="utf-8"))
        assert pack["fact_pack_id"] == payload["pack_id"]

    def test_recorded_answer_keeps_its_refs(self, payload: dict, pack_file: Path) -> None:
        """回归的价值在于「同样的输入必须还能对得上」，所以 refs 必须非空。"""
        answer = payload["answer"]
        refs = [fact.get("ref") for fact in answer.get("facts") or []]
        assert refs and all(refs)
