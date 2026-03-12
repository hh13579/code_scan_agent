from __future__ import annotations

from typing import Any

from code_scan_agent.retrieval.language.common import trim_block
from code_scan_agent.retrieval.specs import ContextBlock

_KIND_PRIORITY = {
    "function_context": 0,
    "ownership_path": 1,
    "sibling_api": 2,
    "helper_definition": 3,
    "cleanup_path": 4,
    "call_site": 5,
    "type_definition": 6,
    "related_test": 7,
}

_ROLE_PRIORITY = {
    "changed_entrypoint": 0,
    "local_changed_logic": 1,
    "helper_definition": 2,
    "ownership_transfer_path": 3,
    "cleanup_path": 4,
    "destructor_or_clear": 5,
    "sibling_baseline": 6,
    "public_contract": 7,
    "declaration_or_type": 8,
    "state_write_point": 9,
    "state_read_point": 10,
    "state_reset_path": 11,
    "call_sites": 12,
    "outward_exposure": 13,
    "related_test": 14,
}


def _coerce_block(item: ContextBlock | dict[str, Any]) -> ContextBlock:
    if isinstance(item, ContextBlock):
        return item
    return ContextBlock(
        file=str(item.get("file", "")).strip(),
        kind=str(item.get("kind", "")).strip(),
        content=str(item.get("content", "")),
        bug_class=str(item.get("bug_class", "")).strip(),
        evidence_role=str(item.get("evidence_role", "")).strip(),
        hop=int(item.get("hop", 0) or 0),
        source_path=str(item.get("source_path", item.get("file", ""))).strip(),
        why_selected=str(item.get("why_selected", "")).strip(),
        subject_file=str(item.get("subject_file", "")).strip(),
        symbol=str(item.get("symbol", "")).strip(),
        priority=int(item.get("priority", 10) or 10),
        max_chars=int(item["max_chars"]) if item.get("max_chars") is not None else None,
        max_lines=int(item["max_lines"]) if item.get("max_lines") is not None else None,
    )


def build_context_bundle(
    blocks: list[ContextBlock | dict[str, Any]],
    *,
    max_blocks: int = 8,
    max_block_chars: int = 1600,
    max_total_chars: int = 12000,
    per_kind_limit: int = 2,
    max_block_lines: int = 800,
) -> list[ContextBlock]:
    bundled: list[ContextBlock] = []
    seen: set[tuple[str, str, str, str, str, int]] = set()
    per_file_kind_count: dict[tuple[str, str, str, str], int] = {}
    total_chars = 0

    indexed_blocks = [(index, _coerce_block(item)) for index, item in enumerate(blocks)]
    indexed_blocks.sort(
        key=lambda pair: (
            int(pair[1].priority),
            int(pair[1].hop),
            _ROLE_PRIORITY.get(pair[1].evidence_role, 99),
            0 if pair[1].subject_file == pair[1].file else 1,
            _KIND_PRIORITY.get(pair[1].kind, 99),
            pair[0],
        )
    )

    for _, item in indexed_blocks:
        item_max_chars = item.max_chars or max_block_chars
        item_max_lines = item.max_lines if item.max_lines is not None else max_block_lines
        content = trim_block(item.content, max_chars=item_max_chars, max_lines=item_max_lines).strip()
        if not item.file or not item.kind or not content:
            continue

        dedupe_key = (
            item.subject_file,
            item.file,
            item.kind,
            item.symbol or content[:160],
            item.evidence_role,
            item.hop,
        )
        if dedupe_key in seen:
            continue
        file_kind_key = (item.subject_file, item.file, item.kind, item.evidence_role)
        if per_file_kind_count.get(file_kind_key, 0) >= per_kind_limit:
            continue
        if len(bundled) >= max_blocks:
            break
        if total_chars + len(content) > max_total_chars:
            break

        bundled.append(
            ContextBlock(
                file=item.file,
                kind=item.kind,
                content=content,
                bug_class=item.bug_class,
                evidence_role=item.evidence_role,
                hop=item.hop,
                source_path=item.source_path,
                why_selected=item.why_selected,
                subject_file=item.subject_file,
                symbol=item.symbol,
                priority=item.priority,
                max_chars=item_max_chars,
                max_lines=item_max_lines,
            )
        )
        seen.add(dedupe_key)
        per_file_kind_count[file_kind_key] = per_file_kind_count.get(file_kind_key, 0) + 1
        total_chars += len(content)

    return bundled


def bundle_context(context_blocks: list[ContextBlock | dict[str, Any]]) -> list[ContextBlock]:
    return build_context_bundle(
        context_blocks,
        max_blocks=18,
        max_block_chars=1800,
        max_total_chars=24000,
        per_kind_limit=3,
        max_block_lines=800,
    )
