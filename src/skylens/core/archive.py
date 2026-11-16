"""fact_pack 快照：每次生成都留档，用于事后复盘与回归样本。

为什么值得存：

- 解释层的回答依赖当时那份事实包；隔天再取数已经变了，无法复现「昨天为什么这么说」；
- M6 回归集需要固定的输入样本，否则每次跑都在跟随机天气比；
- 只写本地磁盘（``~/.cache/skylens/packs``），不外传、不进仓库。

文件名就是 ``fact_pack_id`` 的哈希部分，天然去重。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skylens.settings import Settings


def packs_dir(settings: Settings | None = None) -> Path:
    settings = settings or Settings()
    return settings.cache_dir / "packs"


def pack_path(pack_id: str, root: Path) -> Path:
    digest = pack_id.split(":", 1)[-1]
    return root / f"{digest}.json"


def save_pack(pack: dict[str, Any], root: Path | None = None) -> Path:
    """落盘并返回路径。内容相同的包（同 id）只写一次。"""
    fact_pack_id = str(pack.get("fact_pack_id") or "")
    if not fact_pack_id.startswith("sha256:"):
        raise ValueError("fact_pack 缺少可用的 fact_pack_id，不落盘")
    root = root or packs_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = pack_path(fact_pack_id, root)
    if path.exists():
        return path
    path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_pack(fact_pack_id: str, root: Path | None = None) -> dict[str, Any]:
    root = root or packs_dir()
    path = pack_path(fact_pack_id, root)
    return json.loads(path.read_text(encoding="utf-8"))


def list_packs(root: Path | None = None) -> list[dict[str, Any]]:
    """按时间倒序返回已存档的包（只要摘要，不读全文）。"""
    root = root or packs_dir()
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "fact_pack_id": pack.get("fact_pack_id"),
                "generated_at": pack.get("generated_at"),
                "place": (pack.get("location") or {}).get("name"),
                "path": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return items
