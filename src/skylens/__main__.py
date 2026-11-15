"""``python -m skylens`` 入口：无参数时打印版本，便于建仓阶段自检。"""

from __future__ import annotations

import sys

from skylens import __version__
from skylens.cli import main


def _run() -> int:
    if len(sys.argv) == 1:
        print(f"skylens {__version__}")
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
