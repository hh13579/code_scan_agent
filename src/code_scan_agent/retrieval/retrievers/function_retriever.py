from __future__ import annotations

from pathlib import Path
from typing import Any

from code_scan_agent.retrieval.language.common import normalize_path, read_file_text, safe_slice_lines, trim_block
from code_scan_agent.retrieval.language.cpp_context import find_function_context as find_cpp_function_context
from code_scan_agent.retrieval.language.java_context import find_function_context as find_java_function_context
from code_scan_agent.retrieval.language.ts_context import find_function_context as find_ts_function_context


def retrieve_function_context(
    *,
    repo_path: str | Path,
    file: str,
    language: str,
    changed_lines: list[int],
) -> list[dict[str, Any]]:
    repo_root = Path(repo_path).resolve()
    abs_path = (repo_root / file).resolve()
    text = read_file_text(abs_path)
    if not text:
        return []

    finder = {
        "cpp": find_cpp_function_context,
        "java": find_java_function_context,
        "ts": find_ts_function_context,
    }.get(language)

    if finder:
        block_candidates: list[dict[str, Any]] = []
        seen_ranges: set[tuple[str, int, int]] = set()
        normalized_lines = sorted(line for line in changed_lines if isinstance(line, int) and line > 0)
        for line in normalized_lines:
            result = finder(text, [line])
            if not result:
                continue
            start_line = int(result.get("start_line", 0) or 0)
            end_line = int(result.get("end_line", 0) or 0)
            symbol = str(result.get("symbol", ""))
            key = (symbol, start_line, end_line)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            covered_lines = [item for item in normalized_lines if start_line <= item <= end_line]
            block_candidates.append(
                {
                    "file": normalize_path(file),
                    "kind": "function_context",
                    "symbol": symbol,
                    "content": trim_block(str(result.get("content", "")), max_chars=2200),
                    "_covered_count": len(covered_lines),
                    "_start_line": start_line,
                }
            )

        if block_candidates:
            block_candidates.sort(
                key=lambda item: (
                    -int(item.get("_covered_count", 0)),
                    -int(item.get("_start_line", 0)),
                )
            )
            out: list[dict[str, Any]] = []
            for item in block_candidates[:2]:
                normalized = dict(item)
                normalized.pop("_covered_count", None)
                normalized.pop("_start_line", None)
                out.append(normalized)
            return out

    if changed_lines:
        target_line = min(line for line in changed_lines if isinstance(line, int) and line > 0)
        fallback = safe_slice_lines(text, target_line - 30, target_line + 30)
        if fallback:
            return [
                {
                    "file": normalize_path(file),
                    "kind": "function_context",
                    "symbol": "",
                    "content": trim_block(fallback, max_chars=2200),
                }
            ]

    return []
