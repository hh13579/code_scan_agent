from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from code_scan_agent.retrieval.language.common import (
    find_matching_brace_end,
    guess_symbols_from_patch,
    iter_repo_files,
    normalize_path,
    read_file_text,
    safe_slice_lines,
    trim_block,
)


_LANG_SUFFIXES = {
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".h"},
    "java": {".java"},
    "ts": {".ts", ".tsx"},
}


def _type_patterns(language: str, symbol: str) -> list[re.Pattern[str]]:
    escaped = re.escape(symbol)
    if language == "ts":
        return [
            re.compile(rf"\b(?:export\s+)?(?:interface|type|class|enum)\s+{escaped}\b"),
        ]
    if language == "java":
        return [
            re.compile(rf"\b(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+|static\s+)*(?:class|interface|enum)\s+{escaped}\b"),
        ]
    return [
        re.compile(rf"\b(?:class|struct|enum)\s+{escaped}\b"),
        re.compile(rf"\busing\s+{escaped}\b"),
        re.compile(rf"\btypedef\b.*\b{escaped}\b"),
    ]


def _extract_type_block(text: str, patterns: list[re.Pattern[str]]) -> str:
    lines = text.splitlines()
    for start_line, line in enumerate(lines, start=1):
        for pattern in patterns:
            if not pattern.search(line):
                continue
            if "{" in line:
                end_line = find_matching_brace_end(lines, start_line)
                if end_line is not None:
                    return "\n".join(lines[start_line - 1 : end_line])
            for probe in range(start_line + 1, min(len(lines), start_line + 12) + 1):
                if "{" in lines[probe - 1]:
                    end_line = find_matching_brace_end(lines, probe)
                    if end_line is not None:
                        return "\n".join(lines[start_line - 1 : end_line])
                if ";" in lines[probe - 1]:
                    return safe_slice_lines(text, start_line, probe)
            return safe_slice_lines(text, start_line, min(len(lines), start_line + 20))
    return ""


def _candidate_symbols(patch: str, function_context: dict[str, Any] | None) -> list[str]:
    candidates = guess_symbols_from_patch(patch, max_items=8)
    if function_context:
        content = str(function_context.get("content", ""))
        for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\b", content):
            symbol = match.group(1)
            if symbol not in candidates:
                candidates.append(symbol)
            if len(candidates) >= 8:
                break
    return candidates


def retrieve_type_definitions(
    *,
    repo_path: str | Path,
    file: str,
    language: str,
    patch: str,
    function_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repo_root = Path(repo_path).resolve()
    file_path = (repo_root / file).resolve()
    current_text = read_file_text(file_path)
    if not current_text:
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    symbols = _candidate_symbols(patch, function_context)
    suffixes = _LANG_SUFFIXES.get(language, set())

    for symbol in symbols:
        if len(out) >= 2:
            break
        block = _extract_type_block(current_text, _type_patterns(language, symbol))
        if block:
            key = (normalize_path(file), symbol)
            if key not in seen:
                out.append(
                    {
                        "file": normalize_path(file),
                        "kind": "type_definition",
                        "symbol": symbol,
                        "content": trim_block(block, max_chars=1800),
                    }
                )
                seen.add(key)
                continue

        for candidate in iter_repo_files(repo_root, suffixes):
            rel_path = normalize_path(candidate.relative_to(repo_root))
            if rel_path == normalize_path(file):
                continue
            text = read_file_text(candidate)
            if not text:
                continue
            block = _extract_type_block(text, _type_patterns(language, symbol))
            if not block:
                continue
            key = (rel_path, symbol)
            if key in seen:
                continue
            out.append(
                {
                    "file": rel_path,
                    "kind": "type_definition",
                    "symbol": symbol,
                    "content": trim_block(block, max_chars=1800),
                }
            )
            seen.add(key)
            break

    return out
