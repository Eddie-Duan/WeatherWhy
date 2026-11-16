"""引用校验：解释层每一条 ``ref`` / ``basis`` 都必须能在 fact_pack 里取到值。

这是压住幻觉的关键测试点（见技术说明 §10 的 M3 验收）。规则：

- 支持 ``a.b[0].c`` 形式的路径；
- 目标必须**存在且非 None**——指向 null 字段等同于编造，因为那里本来没有数据。
"""

from __future__ import annotations

import re
from typing import Any

TOKEN_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*|\d+)|\[(\d+)\]")


def resolve_ref(
    pack: dict[str, Any], ref: str, *, allow_container: bool = False
) -> tuple[bool, Any]:
    """解析路径。返回 ``(是否取到值, 值)``，取不到时为 ``(False, None)``。

    两种下标写法都接受：``daily[1].temp_max`` 与 ``daily.1.temp_max``。
    后者是模型（和很多人）的直觉写法，实测 DeepSeek 会混着用，强行只认一种等于自伤。

    ``allow_container``：``inference.basis`` 允许指向对象/数组（「依据：synoptic.pattern」
    是合法的证据引用）；而 ``facts[].ref`` 必须落到具体数值，因为那一行就是要展示的值。
    """
    if not isinstance(ref, str) or not ref:
        return False, None

    current: Any = pack
    consumed = 0
    for match in TOKEN_PATTERN.finditer(ref):
        gap = ref[consumed : match.start()]
        if gap.strip("."):  # 只允许 "." 作为分隔符，其他签名一律视为非法路径
            return False, None
        consumed = match.end()
        key, bracket_index = match.group(1), match.group(2)
        if bracket_index is not None:
            if not isinstance(current, list) or int(bracket_index) >= len(current):
                return False, None
            current = current[int(bracket_index)]
            continue
        if key is not None and key.isdigit():
            if not isinstance(current, list) or int(key) >= len(current):
                return False, None
            current = current[int(key)]
            continue
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]

    if consumed != len(ref) or current is None:
        return False, None
    if isinstance(current, (dict, list)) and not allow_container:
        # facts 的引用必须落在具体数值/字符串上；指向整块对象或数组说明它没真的引用到事实
        return False, None
    return True, current


def unresolved_refs(answer: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    """列出所有解析失败的引用（facts[].ref 与 inference.basis[]）。"""
    broken: list[str] = []
    for fact in answer.get("facts") or []:
        if isinstance(fact, dict) and fact.get("ref"):
            ref = str(fact["ref"])
            if not resolve_ref(pack, ref)[0]:
                broken.append(ref)
    inference = answer.get("inference") or {}
    if isinstance(inference, dict):
        for item in inference.get("basis") or []:
            ref = str(item)
            if not resolve_ref(pack, ref, allow_container=True)[0]:
                broken.append(ref)
    return broken


def assert_refs_resolvable(answer: dict[str, Any], pack: dict[str, Any]) -> None:
    """M3 验收：有不可解析引用就抛 AssertionError，并列出具体路径。"""
    broken = unresolved_refs(answer, pack)
    if broken:
        raise AssertionError(f"解释层引用了 fact_pack 中取不到值的路径：{broken}")


REQUIRED_KEYS = (
    "headline",
    "facts",
    "observed",
    "forecast",
    "inference",
    "uncertainty",
    "advice",
    "not_covered",
    "citations",
)


def missing_keys(answer: dict[str, Any]) -> list[str]:
    return [key for key in REQUIRED_KEYS if key not in answer]


def answer_text(answer: dict[str, Any]) -> str:
    """把回答里所有面向用户的文字拼起来，供「必须声明」类检查用。"""
    parts = [str(answer.get("headline") or "")]
    for key in ("observed", "forecast", "uncertainty", "advice"):
        parts.append(str(answer.get(key) or ""))
    inference = answer.get("inference") or {}
    if isinstance(inference, dict):
        parts.append(str(inference.get("text") or ""))
    return "\n".join(parts)


def assert_answer_invariants(
    answer: dict[str, Any], pack: dict[str, Any], *, allow_degraded: bool = True
) -> None:
    """M6 回归集会跑的那组硬约束。任何一条不满足都算回归失败。

    1. 契约字段齐全；
    2. 每个 ref / basis 都能在 fact_pack 里解析到具体值；
    3. citations 非空（不允许「无源之谈」）；
    4. 降级时必须有 ``fallback_reason`` 且 ``not_covered`` 非空；
    5. 观测代表性为「低」时，回答必须显式声明这一点；
    6. 有官方预警时，回答必须提到「预警」，不能装作没看见。
    """
    problems = [f"缺少字段 {key}" for key in missing_keys(answer)]
    problems.extend(f"引用无法解析：{ref}" for ref in unresolved_refs(answer, pack))
    if not (answer.get("citations") or []):
        problems.append("citations 为空")
    if answer.get("degraded") and not allow_degraded:
        problems.append("本次为降级回答（degraded=true）")
    if answer.get("degraded"):
        if not answer.get("fallback_reason"):
            problems.append("降级回答缺少 fallback_reason")
        if not (answer.get("not_covered") or []):
            problems.append("降级回答的 not_covered 为空")

    observed = pack.get("observed") or {}
    representativeness = observed.get("representativeness") or {}
    text = answer_text(answer)
    if representativeness.get("level") == "低" and "代表性" not in text:
        problems.append("观测代表性为低，但回答没有声明代表性局限")

    if pack.get("warnings") and "预警" not in text:
        problems.append("事实包有官方预警，回答却未提及预警")

    if problems:
        raise AssertionError("；".join(problems))
