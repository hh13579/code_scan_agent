from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parent
    src_dir = root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main() -> int:
    _bootstrap()
    from code_scan_agent.main import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
