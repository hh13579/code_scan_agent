from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from code_scan_agent.retrieval.language.common import (
    extract_line_window,
    guess_symbols_from_patch,
    iter_repo_files,
    normalize_path,
    read_file_text,
    trim_block,
)


_LANG_SUFFIXES = {
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".h"},
    "java": {".java"},
    "ts": {".ts", ".tsx"},
}


def _candidate_symbols(patch: str, function_context: dict[str, Any] | None) -> list[str]:
    candidates = guess_symbols_from_patch(patch, max_items=6)
    if function_context:
        symbol = str(function_context.get("symbol", "")).strip()
        if symbol and symbol not in candidates:
            candidates.insert(0, symbol)
    return candidates[:6]


def retrieve_call_sites(
    *,
    repo_path: str | Path,
    file: str,
    language: str,
    patch: str,
    function_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repo_root = Path(repo_path).resolve()
    source_path = normalize_path(file)
    suffixes = _LANG_SUFFIXES.get(language, set())
    out: list[dict[str, Any]] = []

    for symbol in _candidate_symbols(patch, function_context):
        if len(out) >= 3:
            break
        call_re = re.compile(rf"\b{re.escape(symbol)}\s*\(")
        for candidate in iter_repo_files(repo_root, suffixes):
            rel_path = normalize_path(candidate.relative_to(repo_root))
            text = read_file_text(candidate)
            if not text:
                continue
            lines = text.splitlines()
            for line_no, line in enumerate(lines, start=1):
                if not call_re.search(line):
                    continue
                if rel_path == source_path and function_context and str(function_context.get("symbol", "")) == symbol:
                    declaration_line = str(function_context.get("content", "")).splitlines()[0] if function_context.get("content") else ""
                    if line.strip() == declaration_line.strip():
                        continue
                out.append(
                    {
                        "file": rel_path,
                        "kind": "call_site",
                        "symbol": symbol,
                        "content": trim_block(extract_line_window(text, line_no, before=10, after=10), max_chars=1000),
                    }
                )
                if len(out) >= 3:
                    break
            if len(out) >= 3:
                break

    return out
