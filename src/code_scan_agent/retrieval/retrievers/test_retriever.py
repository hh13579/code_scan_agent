from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from code_scan_agent.retrieval.language.common import (
    extract_line_window,
    guess_symbol_from_patch,
    iter_repo_files,
    normalize_path,
    read_file_text,
    trim_block,
)


_TEST_SUFFIX_BY_LANG = {
    "ts": [".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"],
    "java": ["Test.java"],
    "cpp": ["_test.cpp", "_test.cc", "_test.cxx", "test_.cpp"],
}


def _candidate_test_names(file: str, language: str) -> list[str]:
    path = Path(file)
    stem = path.stem
    names: list[str] = []
    if language == "ts":
        names.extend([f"{stem}.test.ts", f"{stem}.spec.ts", f"{stem}.test.tsx", f"{stem}.spec.tsx"])
    elif language == "java":
        names.append(f"{stem}Test.java")
    elif language == "cpp":
        names.extend([f"{stem}_test.cpp", f"{stem}_test.cc", f"{stem}_test.cxx", f"test_{stem}.cpp"])
    return names


def find_related_tests(
    *,
    repo_path: str | Path,
    file: str,
    language: str,
    patch: str,
    function_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repo_root = Path(repo_path).resolve()
    symbol = str(function_context.get("symbol", "")).strip() if function_context else ""
    if not symbol:
        symbol = guess_symbol_from_patch(patch)

    candidates: list[Path] = []
    candidate_names = set(_candidate_test_names(file, language))
    for path in iter_repo_files(repo_root, None):
        name = path.name
        rel_path = normalize_path(path.relative_to(repo_root))
        if any(part in {"tests", "__tests__", "test"} for part in path.parts) or name in candidate_names:
            if language == "ts" and path.suffix.lower() not in {".ts", ".tsx"}:
                continue
            if language == "java" and path.suffix.lower() != ".java":
                continue
            if language == "cpp" and path.suffix.lower() not in {".cpp", ".cc", ".cxx", ".h", ".hpp"}:
                continue
            candidates.append(path)
        elif name in candidate_names or rel_path.endswith(tuple(candidate_names)):
            candidates.append(path)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    symbol_re = re.compile(rf"\b{re.escape(symbol)}\b") if symbol else None
    test_hint_re = re.compile(r"\b(it|test|TEST|TEST_F|TEST_P|assert|expect)\b")

    for path in candidates:
        rel_path = normalize_path(path.relative_to(repo_root))
        if rel_path in seen:
            continue
        text = read_file_text(path)
        if not text:
            continue

        snippet = ""
        if symbol_re:
            for line_no, line in enumerate(text.splitlines(), start=1):
                if symbol_re.search(line):
                    snippet = extract_line_window(text, line_no, before=12, after=12)
                    break
        if not snippet:
            for line_no, line in enumerate(text.splitlines(), start=1):
                if test_hint_re.search(line):
                    snippet = extract_line_window(text, line_no, before=6, after=18)
                    break
        if not snippet:
            snippet = "\n".join(text.splitlines()[:24])

        if not snippet.strip():
            continue

        out.append(
            {
                "file": rel_path,
                "kind": "related_test",
                "symbol": symbol,
                "content": trim_block(snippet, max_chars=1200),
            }
        )
        seen.add(rel_path)
        if len(out) >= 2:
            break

    return out


def retrieve_related_tests(
    *,
    repo_path: str | Path,
    file: str,
    language: str,
    patch: str,
    function_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return find_related_tests(
        repo_path=repo_path,
        file=file,
        language=language,
        patch=patch,
        function_context=function_context,
    )
