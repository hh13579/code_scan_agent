from __future__ import annotations

import re

from code_scan_agent.retrieval.language.common import extract_enclosing_block


_JAVA_PATTERNS = [
    re.compile(
        r"(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\], ?]+\s+(?P<symbol>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{",
        re.MULTILINE,
    ),
    re.compile(
        r"(?P<symbol>[A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{",
        re.MULTILINE,
    ),
]


def find_function_context(text: str, changed_lines: list[int]) -> dict[str, object] | None:
    result = extract_enclosing_block(text, changed_lines, _JAVA_PATTERNS)
    if result is None:
        return None
    symbol, content, start_line, end_line = result
    return {
        "symbol": symbol,
        "content": content,
        "start_line": start_line,
        "end_line": end_line,
    }
