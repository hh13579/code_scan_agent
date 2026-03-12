from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


_SKIP_DIRS = {".git", "node_modules", "build", "dist", "vendor", "third_party", ".idea", ".vscode"}
_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "case"}


def normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def read_file_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def safe_slice_lines(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    start = max(1, start)
    end = min(len(lines), max(start, end))
    return "\n".join(lines[start - 1 : end])


def line_to_offset(text: str, line_no: int) -> int:
    if line_no <= 1:
        return 0
    lines = text.splitlines(keepends=True)
    return sum(len(line) for line in lines[: max(line_no - 1, 0)])


def trim_block(text: str, max_chars: int = 1600) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max(max_chars - head - 24, 0)
    omitted = len(text) - max_chars
    return f"{text[:head]}\n... {omitted} chars omitted ...\n{text[-tail:]}"


def guess_symbols_from_patch(patch: str, max_items: int = 6) -> list[str]:
    candidates: list[str] = []
    for line in patch.splitlines():
        if not line or line.startswith(("+++", "---", "@@")):
            continue
        raw = line[1:] if line[:1] in {"+", "-"} else line

        for match in re.finditer(r"\b(?:class|interface|struct|enum|type)\s+([A-Za-z_]\w*)", raw):
            symbol = match.group(1)
            if symbol not in candidates:
                candidates.append(symbol)

        for match in re.finditer(r"\bfunction\s+([A-Za-z_]\w*)\s*\(", raw):
            symbol = match.group(1)
            if symbol not in candidates:
                candidates.append(symbol)

        for match in re.finditer(r"\b([A-Za-z_~]\w*)\s*\(", raw):
            symbol = match.group(1)
            if symbol in _CONTROL_KEYWORDS:
                continue
            if symbol not in candidates:
                candidates.append(symbol)

        for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\b", raw):
            symbol = match.group(1)
            if symbol not in candidates:
                candidates.append(symbol)

        if len(candidates) >= max_items:
            break

    return candidates[:max_items]


def guess_symbol_from_patch(patch: str) -> str:
    symbols = guess_symbols_from_patch(patch, max_items=1)
    return symbols[0] if symbols else ""


def extract_line_window(text: str, line_no: int, *, before: int = 12, after: int = 12) -> str:
    return safe_slice_lines(text, line_no - before, line_no + after)


def iter_repo_files(repo_path: Path, suffixes: Iterable[str] | None = None) -> list[Path]:
    suffix_set = {item.lower() for item in suffixes or []}
    paths: list[Path] = []
    try:
        for path in repo_path.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if suffix_set and path.suffix.lower() not in suffix_set:
                continue
            paths.append(path)
    except Exception:
        return []
    return paths


def find_matching_brace_end(lines: list[str], brace_line: int) -> int | None:
    depth = 0
    started = False
    for idx in range(max(brace_line - 1, 0), len(lines)):
        for char in lines[idx]:
            if char == "{":
                depth += 1
                started = True
            elif char == "}":
                if started:
                    depth -= 1
                    if depth == 0:
                        return idx + 1
    return None


def extract_enclosing_block(
    text: str,
    changed_lines: list[int],
    declaration_patterns: list[re.Pattern[str]],
    *,
    search_back_lines: int = 80,
    search_forward_lines: int = 8,
    fallback_radius: int = 30,
) -> tuple[str, str, int, int] | None:
    lines = text.splitlines()
    if not lines:
        return None

    targets = sorted(line for line in changed_lines if isinstance(line, int) and line > 0) or [1]
    for target_line in targets:
        lower_bound = max(1, target_line - search_back_lines)
        for start_line in range(target_line, lower_bound - 1, -1):
            snippet_end = min(len(lines), start_line + search_forward_lines)
            snippet = "\n".join(lines[start_line - 1 : snippet_end])
            matched_symbol = ""
            matched = False
            for pattern in declaration_patterns:
                match = pattern.search(snippet)
                if match:
                    matched_symbol = str(match.groupdict().get("symbol", "")).strip()
                    matched = True
                    break
            if not matched:
                continue

            brace_line = None
            for probe_line in range(start_line, min(len(lines), start_line + search_forward_lines) + 1):
                if "{" in lines[probe_line - 1]:
                    brace_line = probe_line
                    break
            if brace_line is None:
                continue

            end_line = find_matching_brace_end(lines, brace_line)
            if end_line is None or end_line < target_line:
                continue

            content = "\n".join(lines[start_line - 1 : end_line])
            return matched_symbol, content, start_line, end_line

    target_line = targets[0]
    start_line = max(1, target_line - fallback_radius)
    end_line = min(len(lines), target_line + fallback_radius)
    return "", "\n".join(lines[start_line - 1 : end_line]), start_line, end_line
