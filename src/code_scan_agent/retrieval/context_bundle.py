from __future__ import annotations

from typing import Any

from code_scan_agent.retrieval.language.common import trim_block


def build_context_bundle(
    blocks: list[dict[str, Any]],
    *,
    max_blocks: int = 8,
    max_block_chars: int = 1600,
    max_total_chars: int = 12000,
    per_kind_limit: int = 2,
) -> list[dict[str, Any]]:
    bundled: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    per_file_kind_count: dict[tuple[str, str], int] = {}
    total_chars = 0

    for item in blocks:
        file_path = str(item.get("file", "")).strip()
        kind = str(item.get("kind", "")).strip()
        content = trim_block(str(item.get("content", "")), max_chars=max_block_chars).strip()
        symbol = str(item.get("symbol", "")).strip()
        if not file_path or not kind or not content:
            continue

        dedupe_key = (file_path, kind, symbol or content[:160])
        if dedupe_key in seen:
            continue
        file_kind_key = (file_path, kind)
        if per_file_kind_count.get(file_kind_key, 0) >= per_kind_limit:
            continue
        if len(bundled) >= max_blocks:
            break
        if total_chars + len(content) > max_total_chars:
            break

        normalized = {
            "file": file_path,
            "kind": kind,
            "content": content,
        }
        if symbol:
            normalized["symbol"] = symbol
        subject_file = str(item.get("subject_file", "")).strip()
        if subject_file:
            normalized["subject_file"] = subject_file

        bundled.append(normalized)
        seen.add(dedupe_key)
        per_file_kind_count[file_kind_key] = per_file_kind_count.get(file_kind_key, 0) + 1
        total_chars += len(content)

    return bundled
