"""引用校验：解释层每一条 ``ref`` / ``basis`` 都必须能在 fact_pack 里取到值。

这是压住幻觉的关键测试点（见技术说明 §10 的 M3 验收）。规则：

- 支持 ``a.b[0].c`` 形式的路径；
- 目标必须**存在且非 None**——指向 null 字段等同于编造，因为那里本来没有数据。
"""

from __future__ import annotations

import re
from typing import Any

TOKEN_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def resolve_ref(pack: dict[str, Any], ref: str) -> tuple[bool, Any]:
    """解析路径。返回 ``(是否取到值, 值)``，取不到时为 ``(False, None)``。"""
    if not isinstance(ref, str) or not ref:
        return False, None

    current: Any = pack
    consumed = 0
    for match in TOKEN_PATTERN.finditer(ref):
        gap = ref[consumed : match.start()]
        if gap.strip("."):  # 只允许 "." 作为分隔符，其他签名一律视为非法路径
            return False, None
        consumed = match.end()
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                return False, None
            current = current[key]
        else:
            if not isinstance(current, list) or int(index) >= len(current):
                return False, None
            current = current[int(index)]

    if consumed != len(ref) or current is None:
        return False, None
    if isinstance(current, (dict, list)):
        # 引用必须落在具体数值/字符串上；指向整块对象或数组说明它没真的引用到事实
        return False, None
    return True, current


def unresolved_refs(answer: dict[str, Any], pack: dict[str, Any]) -> list[str]:
    """列出所有解析失败的引用（facts[].ref 与 inference.basis[]）。"""
    refs: list[str] = []
    for fact in answer.get("facts") or []:
        if isinstance(fact, dict) and fact.get("ref"):
            refs.append(str(fact["ref"]))
    inference = answer.get("inference") or {}
    if isinstance(inference, dict):
        refs.extend(str(item) for item in (inference.get("basis") or []))

    return [ref for ref in refs if not resolve_ref(pack, ref)[0]]


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
