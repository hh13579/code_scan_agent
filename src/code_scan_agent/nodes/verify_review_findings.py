from __future__ import annotations

from typing import Any

from code_scan_agent.graph.state import GraphState


_REVIEW_ACTION_ORDER = {"block": 0, "should_fix": 1, "follow_up": 2}
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _severity_of(item: dict[str, Any]) -> str:
    severity = str(item.get("severity", "info")).strip().lower()
    return severity if severity in _SEVERITY_ORDER else "info"


def _review_action_of(item: dict[str, Any]) -> str:
    action = str(item.get("review_action", "")).strip().lower()
    return action if action in _REVIEW_ACTION_ORDER else ""


def _has_evidence(item: dict[str, Any]) -> bool:
    evidence = item.get("evidence", [])
    if isinstance(evidence, list):
        return any(str(entry).strip() for entry in evidence)
    return bool(str(evidence).strip())


def _item_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _related_context_blocks(
    review_context_blocks: list[Any],
    file_path: str,
) -> list[Any]:
    related: list[Any] = []
    for block in review_context_blocks:
        subject_file = str(_item_value(block, "subject_file", "")).strip()
        block_file = str(_item_value(block, "file", "")).strip()
        if file_path and (subject_file == file_path or block_file == file_path):
            related.append(block)
    return related


def _verification_sort_key(item: dict[str, Any]) -> tuple[int, int, str, int]:
    return (
        _REVIEW_ACTION_ORDER.get(_review_action_of(item), 99),
        _SEVERITY_ORDER.get(_severity_of(item), 99),
        str(item.get("file", "")),
        int(item.get("line") or 10**9),
    )


def _verify_one(
    finding: dict[str, Any],
    review_context_blocks: list[Any],
) -> tuple[str, list[str]]:
    file_path = str(finding.get("file", "")).strip()
    related_blocks = _related_context_blocks(review_context_blocks, file_path)
    kinds = {str(_item_value(item, "kind", "")).strip() for item in related_blocks}
    notes: list[str] = []

    evidence_ok = _has_evidence(finding)
    if evidence_ok:
        notes.append("finding 自带 evidence。")
    else:
        notes.append("finding 缺少直接 evidence。")

    if "function_context" in kinds:
        notes.append("已找到对应函数上下文。")
    if "type_definition" in kinds:
        notes.append("已找到相关类型定义。")
    if "related_test" in kinds:
        notes.append("已找到相关测试片段。")
    if "helper_definition" in kinds:
        notes.append("已找到 helper / 隐式分配定义。")
    if "cleanup_path" in kinds:
        notes.append("已找到 save/release/pool/clear 清理链上下文。")
    if "sibling_api" in kinds:
        notes.append("已找到 sibling API 对照。")

    if evidence_ok and kinds.intersection({"type_definition", "related_test", "function_context", "helper_definition", "cleanup_path", "sibling_api"}):
        return "strengthened", notes
    if not evidence_ok and not kinds.intersection({"function_context", "type_definition", "related_test", "helper_definition", "cleanup_path", "sibling_api"}):
        return "weak", notes
    return "unchanged", notes


def verify_review_findings(state: GraphState) -> GraphState:
    findings = [dict(item) for item in state.get("llm_review_findings", [])]
    if not findings:
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append("verify_review_findings: skipped (no llm_review_findings)")
        return state

    review_context_blocks = list(state.get("review_context_blocks", []))
    for item in findings:
        item["verification_status"] = str(item.get("verification_status", "")).strip() or "unchanged"
        if "verification_notes" not in item:
            item["verification_notes"] = []

    strengthened = 0
    weakened = 0
    for finding in sorted(findings, key=_verification_sort_key)[:3]:
        status, notes = _verify_one(finding, review_context_blocks)
        finding["verification_status"] = status
        finding["verification_notes"] = notes
        if status == "strengthened":
            strengthened += 1
        elif status == "weak":
            weakened += 1

    state["llm_review_findings"] = findings
    state.setdefault("logs", []).append(
        "verify_review_findings: "
        f"checked={min(len(findings), 3)}, strengthened={strengthened}, weak={weakened}"
    )
    return state
