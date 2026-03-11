from __future__ import annotations

import os
from pathlib import Path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_local_env() -> Path | None:
    candidates = [
        Path.cwd() / ".env.local",
        Path(__file__).resolve().parents[3] / ".env.local",
    ]

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        for raw in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _parse_env_line(raw)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
        return candidate
    return None
