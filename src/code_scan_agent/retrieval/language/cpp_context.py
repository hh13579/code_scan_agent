from __future__ import annotations

import re

from code_scan_agent.retrieval.language.common import extract_enclosing_block


_CPP_PATTERNS = [
    re.compile(
        r"(?P<symbol>[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)?)\s*\([^;{}]*\)\s*(?:const)?\s*(?:noexcept)?\s*\{",
        re.MULTILINE,
    ),
    re.compile(
        r"(?:[\w:<>,~*&\s]+)\b(?P<symbol>[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)?)\s*\([^;{}]*\)",
        re.MULTILINE,
    ),
]


def find_function_context(text: str, changed_lines: list[int]) -> dict[str, object] | None:
    result = extract_enclosing_block(text, changed_lines, _CPP_PATTERNS)
    if result is None:
        return None
    symbol, content, start_line, end_line = result
    return {
        "symbol": symbol.split("::")[-1] if symbol else "",
        "content": content,
        "start_line": start_line,
        "end_line": end_line,
    }
