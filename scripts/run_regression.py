"""M6 回归集：同一批问题跑解释层，逐条检查「不许编造」的硬约束。

三种模式（都在仓库根目录跑）：

    python scripts/run_regression.py --offline   # 只回放已录制的答案，不花钱、CI 可用
    python scripts/run_regression.py --record    # 真实调用一遍并把答案录成基线（会花钱）
    python scripts/run_regression.py --live      # 真实调用并当场判定，不落盘（nightly 用）

判定项见 ``core.validate.assert_answer_invariants``：契约字段、每个 ref 可解析、
citations 非空、代表性低必须声明、有预警必须提及、降级必须给出原因与未覆盖项。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "regression"
QUESTIONS = FIXTURES / "questions.json"

from skylens.core import archive, validate  # noqa: E402  （路径确定后再导入）
from skylens.core.explain import explain  # noqa: E402
from skylens.core.fact_pack import build_fact_pack  # noqa: E402


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


async def build_packs(places: list[str]) -> dict[str, dict]:
    """每个地点只取一次数（事实包与具体问题无关）。"""
    packs: dict[str, dict] = {}
    for place in places:
        print(f"  取数：{place} …", flush=True)
        pack = await build_fact_pack(place)
        if "error" in pack:
            print(f"  !! {place} 取数失败：{pack['error']}")
            continue
        packs[place] = pack
        archive.save_pack(pack)
    return packs


def check(answer: dict, pack: dict) -> list[str]:
    try:
        validate.assert_answer_invariants(answer, pack)
        return []
    except AssertionError as exc:
        return str(exc).split("；")


def render(report: list[dict]) -> int:
    ok = [item for item in report if not item["problems"]]
    degraded = [item for item in report if item.get("degraded")]
    print(f"\n{'=' * 70}")
    print(f"回归结果：{len(ok)}/{len(report)} 通过｜降级 {len(degraded)} 条")
    for item in report:
        mark = "PASS" if not item["problems"] else "FAIL"
        print(f"  [{mark}] {item['id']} {item['place']}｜{item['question'][:28]}")
        if item["problems"]:
            for problem in item["problems"]:
                print(f"         - {problem}")
    return 0 if len(ok) == len(report) else 1


async def run_live(record: bool) -> int:
    questions = load_questions()
    packs = await build_packs(sorted({item["place"] for item in questions}))
    if record:
        (FIXTURES / "packs").mkdir(parents=True, exist_ok=True)
        (FIXTURES / "answers").mkdir(parents=True, exist_ok=True)

    report: list[dict] = []
    for item in questions:
        pack = packs.get(item["place"])
        if pack is None:
            report.append({**item, "problems": ["事实包取数失败"], "degraded": True})
            continue
        answer = await explain(pack)
        problems = check(answer, pack)
        report.append(
            {
                **item,
                "pack_id": pack["fact_pack_id"],
                "degraded": bool(answer.get("degraded")),
                "problems": problems,
            }
        )
        if record:
            (FIXTURES / "packs" / f"{pack['fact_pack_id'].split(':')[-1]}.json").write_text(
                json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (FIXTURES / "answers" / f"{item['id']}.json").write_text(
                json.dumps(
                    {
                        "id": item["id"],
                        "place": item["place"],
                        "question": item["question"],
                        "pack_id": pack["fact_pack_id"],
                        "answer": answer,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        verdict = "PASS" if not problems else "FAIL"
        print(f"  {item['id']} {verdict}（降级={answer.get('degraded')}）")
    return render(report)


def run_offline() -> int:
    answers_dir = FIXTURES / "answers"
    packs_dir = FIXTURES / "packs"
    if not answers_dir.is_dir():
        print("没有录制的答案，先跑 --record")
        return 1
    report: list[dict] = []
    for path in sorted(answers_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        pack_file = packs_dir / f"{payload['pack_id'].split(':')[-1]}.json"
        if not pack_file.exists():
            report.append(
                {
                    "id": payload["id"],
                    "place": payload["place"],
                    "question": payload["question"],
                    "problems": [f"缺少事实包快照 {pack_file.name}"],
                    "degraded": bool(payload["answer"].get("degraded")),
                }
            )
            continue
        pack = json.loads(pack_file.read_text(encoding="utf-8"))
        report.append(
            {
                "id": payload["id"],
                "place": payload["place"],
                "question": payload["question"],
                "degraded": bool(payload["answer"].get("degraded")),
                "problems": check(payload["answer"], pack),
            }
        )
    return render(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="WeatherWhy M6 回归集")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="回放录制的答案（不花钱）")
    mode.add_argument("--record", action="store_true", help="真实调用并录制基线（会花钱）")
    mode.add_argument("--live", action="store_true", help="真实调用并当场判定")
    args = parser.parse_args()

    if args.offline:
        return run_offline()
    return asyncio.run(run_live(record=args.record))


if __name__ == "__main__":
    sys.exit(main())
