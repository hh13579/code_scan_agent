from __future__ import annotations

from pathlib import Path


_CURRENT_DIR = Path(__file__).resolve().parent
_SRC_PACKAGE_DIR = _CURRENT_DIR.parent / "src" / "code_scan_agent"

if _SRC_PACKAGE_DIR.is_dir():
    __path__.append(str(_SRC_PACKAGE_DIR))  # type: ignore[name-defined]

